"""The appeal remedy's four hops, and the expiry sweep's three."""
from test_helpers import factories, validate_paginated, validate_success
from test_helpers.fixtures import (
    create_applicant,
    heard_appeal_on_paper,
    issued_determination,
    run_day_close,
    set_clock,
)
from test_helpers.test_users import (
    CLERK_HEADERS,
    REVIEWER_HEADERS,
    SPECIALIST_HEADERS,
    TRAINER_HEADERS,
)


def _heard_appeal_against_an_ineligible_grant(api):
    """An INELIGIBLE grant of 2026-08-06, appealed on paper and already HEARD."""
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Priya Raman",
        date_of_birth="1975-01-14",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )
    context = issued_determination(
        api,
        applicant=rider,
        score_overrides={
            "board_alight_score": 4,
            "wayfinding_score": 4,
            "distance_meters_walked": 900,
            "heat_sensitivity_flag": False,
        },
        draft_overrides={
            "category": "INELIGIBLE",
            "effective_date": "2026-08-06",
            "rationale": "Independent on fixed route at all times per observed scores",
        },
    )
    set_clock(api, "2026-08-20T00:00:00Z")
    return heard_appeal_on_paper(
        api,
        context=context,
        reviewer_user_id="rev-1",
    )


def test_overturning_an_appeal_vacates_the_grant_and_mints_a_remedy_successor(api):
    """Hops one and two of the remedy cascade land inside the decision request.

    "**Hop 1:** the appeal moves `HEARD → DECIDED` with `outcome` set from the
    request and `decided_at` stamped from the clock."

    "**Hop 2**, caused by hop 1: the contested determination moves `ISSUED →
    VACATED` with `under_appeal` set to false, and a successor determination is
    created already in `ISSUED`, with `origin` `APPEAL_REMEDY`, `category` equal
    to the appeal's `granted_category`, `effective_date` equal to the calendar
    date of `decided_at`, `term_days` and `expires_at` computed from that category
    and effective date by the same term table used at ordinary issuance,
    `application_id` and `applicant_id` copied from the vacated determination, and
    `determined_by_user_id` set to the appeal's own `reviewer_user_id`."

    Design: Difficulty/transitive_cascade/appeal_overturn_four_hop_cascade_to_auto_travel_training_referral
    """
    context = _heard_appeal_against_an_ineligible_grant(api)
    assert context["appeal"]["decision_due_date"] == "2026-09-19"

    decided = validate_success(
        api.decide_appeal(
            context["appeal"]["id"],
            factories.appeal_decision_payload(
                "OVERTURNED",
                granted_category="CONDITIONAL",
                decision_note="Conditional eligibility for heat and unfamiliar-route trips",
            ),
            REVIEWER_HEADERS,
        )
    )

    assert decided["status"] == "DECIDED"
    assert decided["outcome"] == "OVERTURNED"
    assert decided["decided_at"] == "2026-08-20T00:00:00.000Z"
    assert decided["continued_service_extended"] is False

    contested = validate_success(
        api.get_determination(context["determination"]["id"], SPECIALIST_HEADERS)
    )
    assert contested["status"] == "VACATED"
    assert contested["under_appeal"] is False

    successors, meta = validate_paginated(
        api.list_determinations(
            SPECIALIST_HEADERS,
            params={
                "applicant_id": context["applicant"]["id"],
                "origin": "APPEAL_REMEDY",
            },
        )
    )
    assert meta["total_count"] == 1
    successor = successors[0]
    assert successor["origin"] == "APPEAL_REMEDY"
    assert successor["status"] == "ISSUED"
    assert successor["category"] == "CONDITIONAL"
    assert successor["effective_date"] == "2026-08-20"
    assert successor["term_days"] == 1095
    assert successor["expires_at"] == "2029-08-19"
    assert successor["determined_by_user_id"] == "rev-1"
    assert successor["trip_condition_count"] == 0


def test_the_remedy_cascade_reaches_the_rider_mirrors_and_the_auto_referral(api):
    """Hops three and four follow from the successor grant, not from the request.

    "**Hop 3**, caused by hop 2 because a new issued determination now exists: the
    rider's `current_eligibility_status` becomes `ELIGIBLE`,
    `eligibility_category` becomes the granted category,
    `active_determination_id` becomes the successor's identifier, and
    `continued_service_during_appeal` returns to false."

    "**Hop 4**, caused by hop 3 because the rider now holds conditional
    eligibility: when the granted category is `CONDITIONAL`, a travel-training
    referral is created for the rider with `referral_reason`
    `CONDITIONAL_ELIGIBILITY_AUTO`, `determination_id` pointing at the successor
    determination, and `status` `REFERRED`."

    Design: Difficulty/transitive_cascade/appeal_overturn_four_hop_cascade_to_auto_travel_training_referral
    """
    context = _heard_appeal_against_an_ineligible_grant(api)

    validate_success(
        api.decide_appeal(
            context["appeal"]["id"],
            factories.appeal_decision_payload(
                "OVERTURNED", granted_category="CONDITIONAL"
            ),
            REVIEWER_HEADERS,
        )
    )

    successors, _meta = validate_paginated(
        api.list_determinations(
            SPECIALIST_HEADERS,
            params={
                "applicant_id": context["applicant"]["id"],
                "origin": "APPEAL_REMEDY",
            },
        )
    )
    successor = successors[0]

    rider = validate_success(
        api.get_applicant(context["applicant"]["id"], CLERK_HEADERS)
    )
    assert rider["current_eligibility_status"] == "ELIGIBLE"
    assert rider["eligibility_category"] == "CONDITIONAL"
    assert rider["active_determination_id"] == successor["id"]
    assert rider["continued_service_during_appeal"] is False

    referrals, referral_meta = validate_paginated(
        api.list_travel_training_referrals(
            TRAINER_HEADERS, params={"applicant_id": context["applicant"]["id"]}
        )
    )
    assert referral_meta["total_count"] == 1
    referral = referrals[0]
    assert referral["status"] == "REFERRED"
    assert referral["referral_reason"] == "CONDITIONAL_ELIGIBILITY_AUTO"
    assert referral["determination_id"] == successor["id"]
    assert referral["referral_response_deadline_date"] == "2026-09-03"


def _conditional_grant_expiring_in_2029(api):
    """A CONDITIONAL grant effective 2026-08-06, so it expires on 2029-08-05."""
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Gus Ferreira",
        date_of_birth="1960-03-27",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="WALKER",
    )
    context = issued_determination(
        api,
        applicant=rider,
        draft_overrides={
            "category": "CONDITIONAL",
            "effective_date": "2026-08-06",
            "rationale": "Conditional on heat index",
            "trip_conditions": [
                factories.trip_condition_payload(
                    condition_type="HEAT_INDEX_ABOVE",
                    comparator="GTE",
                    threshold_value=90,
                    note="Paratransit applies when the heat index reaches 90F",
                )
            ],
        },
    )
    referrals, _meta = validate_paginated(
        api.list_travel_training_referrals(
            TRAINER_HEADERS, params={"applicant_id": context["applicant"]["id"]}
        )
    )
    context["referral"] = referrals[0]
    return context


def test_the_expiry_sweep_expires_the_grant_and_clears_the_rider_mirrors(api):
    """Hops one and two of the expiry cascade, driven by the day-close sweep.

    "**Hop 1:** the determination moves `ISSUED → EXPIRED`. **Hop 2**, caused by
    hop 1: the rider's `current_eligibility_status` becomes `EXPIRED`,
    `eligibility_category` becomes null, and `active_determination_id` becomes
    null."

    "**Step 3 — determination expiry.** Every `Determination` in `ISSUED` with a
    non-null `expires_at` that is at or before today's date expires, triggering
    the three-hop cascade described in §3.5."

    Design: Difficulty/transitive_cascade/determination_expiry_three_hop_cascade_withdraws_travel_training
    """
    context = _conditional_grant_expiring_in_2029(api)
    assert context["determination"]["term_days"] == 1095
    assert context["determination"]["expires_at"] == "2029-08-05"

    set_clock(api, "2029-08-05T00:00:00Z")
    sweep = run_day_close(api)

    assert sweep["determinations_expired_count"] == 1
    assert sweep["referrals_withdrawn_count"] == 1
    assert sweep["presumptive_granted_count"] == 0

    determination = validate_success(
        api.get_determination(context["determination"]["id"], SPECIALIST_HEADERS)
    )
    assert determination["status"] == "EXPIRED"

    rider = validate_success(
        api.get_applicant(context["applicant"]["id"], CLERK_HEADERS)
    )
    assert rider["current_eligibility_status"] == "EXPIRED"
    assert rider["eligibility_category"] is None
    assert rider["active_determination_id"] is None


def test_the_expiry_cascade_withdraws_the_referral_and_does_not_repeat(api):
    """Hop three withdraws the training referral, and a second sweep changes nothing.

    "**Hop 3**, caused by hop 2 because the rider is no longer eligible: every
    travel-training referral of that rider sitting in `REFERRED` or `ENROLLED`
    moves to `WITHDRAWN` with `withdrawal_reason` `ELIGIBILITY_LAPSED`."

    "The sweep is idempotent at a fixed clock: invoking it twice without moving
    the clock changes nothing on the second call."

    Design: Difficulty/transitive_cascade/determination_expiry_three_hop_cascade_withdraws_travel_training
    """
    context = _conditional_grant_expiring_in_2029(api)

    set_clock(api, "2029-08-05T00:00:00Z")
    run_day_close(api)

    referral = validate_success(
        api.get_travel_training_referral(context["referral"]["id"], TRAINER_HEADERS)
    )
    assert referral["status"] == "WITHDRAWN"
    assert referral["withdrawal_reason"] == "ELIGIBILITY_LAPSED"

    second_sweep = run_day_close(api)
    assert second_sweep["determinations_expired_count"] == 0
    assert second_sweep["referrals_withdrawn_count"] == 0
