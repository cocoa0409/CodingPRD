"""The reasonable alternative standard: assignment cap, denial and the deep cascade."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_alternative_standard,
    assert_period_money_conservation,
    assert_same_date,
    assign_alternative,
    make_navigator_headers,
    read_period,
    request_alternative,
    setup_high_risk_assessment,
    validate_error,
    validate_paginated,
    validate_success,
)


def _ras_world(code, name, member, wellness_budget=250000, with_period=False):
    kwargs = {
        "employer": {
            "legal_name": name,
            "employer_code": code,
            "wellness_budget_cents": wellness_budget,
        },
        "site": {"site_name": f"{code} Clinic", "daily_slot_capacity": 8},
        "eligibility": {
            "subscriber_external_id": f"S-{member}",
            "member_external_id": f"M-{member}",
        },
        "participant": {"display_name": f"{code} Tester"},
    }
    if with_period:
        kwargs["reporting_period"] = {}
    return setup_high_risk_assessment(**kwargs)


def test_second_reassignment_of_an_alternative_is_rejected():
    """PRD §3.6: "**Assignment** moves the request `REQUESTED → ASSIGNED`, stores the
    chosen `alternative_type` — one of `COACHING_PROGRAM`, `EDUCATION_MODULE` or
    `PHYSICIAN_ALTERNATIVE` — stamps `assigned_at` with the clock instant, and sets
    `due_date` to the assignment date plus ninety days. Exactly one re-assignment is
    permitted: an already-`ASSIGNED` request may be assigned again, which replaces
    `alternative_type`, resets `assigned_at` and `due_date` from the new assignment
    date and raises `reassignment_count` to 1, and a second re-assignment is refused
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/alternative_standard_second_reassignment_rejected
    """
    world = _ras_world("RAS2", "Reassign Co", "3701")
    standard = request_alternative(
        world.participant_id,
        world.assessment_id,
        requested_reason="Cannot meet the outcome standard",
    )
    assert_alternative_standard(standard)
    assert standard["status"] == "REQUESTED"

    first = assign_alternative(standard["id"], world.navigator_id, "COACHING_PROGRAM")
    assert first["status"] == "ASSIGNED"
    assert first["reassignment_count"] == 0
    assert_same_date(first["due_date"], "2026-09-06")

    second = assign_alternative(standard["id"], world.navigator_id, "EDUCATION_MODULE")
    assert second["reassignment_count"] == 1
    assert second["alternative_type"] == "EDUCATION_MODULE"
    assert second["status"] == "ASSIGNED"

    validate_error(
        api_client.assign_alternative_standard(
            standard["id"],
            {"alternative_type": "PHYSICIAN_ALTERNATIVE"},
            make_navigator_headers(world.navigator_id),
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
        409,
    )

    final = validate_success(
        api_client.get_alternative_standard(
            standard["id"], make_navigator_headers(world.navigator_id)
        )
    )
    assert final["reassignment_count"] == 1
    assert final["alternative_type"] == "EDUCATION_MODULE"


def test_denied_alternative_grants_no_credit_and_no_award():
    """PRD §3.6: "**Denial** moves the request `REQUESTED → DENIED`, and its
    consequence is stated as much by what it does not do as by what it does: the
    backing assessment keeps `outcome_credit_status` at `PENDING_ALTERNATIVE`, no
    credit is granted, no incentive award is created, and no period or employer money
    moves."

    Design: Corner/state_machines/alternative_standard_denied_is_terminal_and_grants_no_credit
    """
    world = _ras_world("DNY", "Deny Co", "4201", with_period=True)
    standard = request_alternative(
        world.participant_id, world.assessment_id, requested_reason="Unable to meet standard"
    )

    denied = validate_success(
        api_client.deny_alternative_standard(
            standard["id"], make_navigator_headers(world.navigator_id)
        )
    )
    assert denied["status"] == "DENIED"
    assert denied["credit_granted"] is False

    assessment = validate_success(
        api_client.get_health_assessment(world.assessment_id, world.clinician_headers)
    )
    assert assessment["outcome_credit_status"] == "PENDING_ALTERNATIVE"

    _, meta = validate_paginated(
        api_client.list_incentive_awards(
            world.employer_headers, params={"participant_id": world.participant_id}
        )
    )
    assert meta["total_count"] == 0

    period = read_period(world.period_id)
    assert period["incentive_awarded_cents"] == 0

    validate_error(
        api_client.complete_alternative_standard(
            standard["id"], make_navigator_headers(world.navigator_id)
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
        409,
    )


def test_completion_credits_the_assessment_and_creates_a_retroactive_award():
    """PRD §3.6: "On success five effects land in order. The request moves to
    `COMPLETED` and `credit_granted` becomes true. Caused by that, the backing
    `HealthAssessment` moves `outcome_credit_status` to `CREDITED_VIA_RAS` — while
    `outcome_standard_met` **keeps its original false value**, because the participant
    earned credit through the alternative rather than by meeting the standard. Caused
    by that, an `IncentiveAward` of `award_type` `OUTCOME_BASED` is created for the
    participant with `retroactive` true, `status` `PENDING` and `award_amount_cents`
    of 60000, and it is created in the reporting period whose closed span contains the
    assessment's `measurement_date` — **the original measurement period, not the
    period containing the completion date.**"

    Design: Difficulty/transitive_cascade/ras_completion_cascades_five_hops_to_employer_wellness_budget
    """
    world = _ras_world("RAS", "RAS Co", "9001", wellness_budget=500000, with_period=True)
    standard = request_alternative(
        world.participant_id,
        world.assessment_id,
        requested_reason="Outcome standard medically inadvisable",
    )
    assign_alternative(standard["id"], world.navigator_id, "COACHING_PROGRAM")

    completed = validate_success(
        api_client.complete_alternative_standard(
            standard["id"], make_navigator_headers(world.navigator_id)
        )
    )
    assert completed["status"] == "COMPLETED"
    assert completed["credit_granted"] is True

    assessment = validate_success(
        api_client.get_health_assessment(world.assessment_id, world.clinician_headers)
    )
    assert assessment["outcome_credit_status"] == "CREDITED_VIA_RAS"
    assert assessment["outcome_standard_met"] is False
    assert assessment["risk_points_total"] == 14

    awards, meta = validate_paginated(
        api_client.list_incentive_awards(
            world.employer_headers, params={"participant_id": world.participant_id}
        )
    )
    assert meta["total_count"] == 1
    award = awards[0]
    assert award["award_type"] == "OUTCOME_BASED"
    assert award["award_amount_cents"] == 60000
    assert award["retroactive"] is True
    assert award["status"] == "PENDING"
    assert award["reporting_period_id"] == world.period_id


def test_completion_cascade_reaches_period_buckets_and_employer_budget():
    """PRD §3.6: "Caused by that, that reporting period recomputes
    `incentive_awarded_cents` and `incentive_pending_cents`. And caused by that, the
    employer recomputes `wellness_budget_committed_cents` and
    `wellness_budget_remaining_cents`."
    PRD §3.3: "the two derived figures `completed_visit_count` — this participant's
    visits whose `encounter_status` is `COMPLETED`, `AMENDED` or `LOCKED` — and
    `incentive_awarded_cents` — the sum of `award_amount_cents` across this
    participant's awards in any status — both start at 0."

    Design: Difficulty/transitive_cascade/ras_completion_cascades_five_hops_to_employer_wellness_budget
    """
    world = _ras_world("RAS", "RAS Co", "9001", wellness_budget=500000, with_period=True)
    standard = request_alternative(
        world.participant_id,
        world.assessment_id,
        requested_reason="Outcome standard medically inadvisable",
    )
    assign_alternative(standard["id"], world.navigator_id, "COACHING_PROGRAM")

    validate_success(
        api_client.complete_alternative_standard(
            standard["id"], make_navigator_headers(world.navigator_id)
        )
    )

    period = read_period(world.period_id)
    assert period["incentive_awarded_cents"] == 60000
    assert period["incentive_pending_cents"] == 60000
    assert_period_money_conservation(period)

    employer = validate_success(
        api_client.get_employer(world.employer_id, world.employer_headers)
    )
    assert employer["wellness_budget_committed_cents"] == 60000
    assert employer["wellness_budget_remaining_cents"] == 440000

    participant = validate_success(
        api_client.get_participant(world.participant_id, world.employer_headers)
    )
    assert participant["incentive_awarded_cents"] == 60000
