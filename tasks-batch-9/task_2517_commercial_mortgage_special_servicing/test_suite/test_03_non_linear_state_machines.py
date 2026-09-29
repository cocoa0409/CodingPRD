"""Non-linear state machines: the loan's two independent status dimensions, the
capped information-request cycle and the capped plan revision cycle.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import NPV_MOD_NPV_CONTRACTUAL
from test_helpers.test_users import ASSET_MANAGER, COMMITTEE_OFFICER, MASTER_SERVICER


# ==========================================================================
# The two independent status dimensions on one loan row
# ==========================================================================
def _fresh_loan(api):
    trust = fx.create_trust(api, deal_name="CMBS 2026-D1")
    loan = validate_success(
        api.create_loan(
            f.loan_payload(
                trust["id"],
                loan_number="L-D01",
                original_balance_usd=9000000,
                current_principal_balance_usd=8500000,
                note_rate_pct=5.5,
                monthly_debt_service_usd=52000,
                maturity_date="2030-01-01T00:00:00Z",
                securitization_value_usd=12000000,
            ),
            MASTER_SERVICER,
        ),
        201,
    )
    return trust["id"], loan["id"]


def _walk_the_delinquency_ladder(api, loan_id):
    validate_success(
        api.set_loan_payment_status(
            loan_id,
            {"to_status": "DELINQUENT_30", "as_of_date": "2026-08-05T00:00:00Z"},
            MASTER_SERVICER,
        )
    )
    validate_success(
        api.set_loan_payment_status(
            loan_id,
            {"to_status": "DELINQUENT_60", "as_of_date": "2026-09-04T00:00:00Z"},
            MASTER_SERVICER,
        )
    )
    return validate_success(
        api.set_loan_payment_status(
            loan_id,
            {"to_status": "DELINQUENT_90_PLUS", "as_of_date": "2026-10-04T00:00:00Z"},
            MASTER_SERVICER,
        )
    )


def test_the_payment_ladder_moves_without_touching_the_servicing_dimension(api):
    """Three delinquency rungs leave servicing_status at MASTER_SERVICING.

    The PRD: "A loan carries **two independent status dimensions on one row**,
    and neither gates the other except where a precondition says so in as many
    words."

    Design: Difficulty/non_linear_state_machine/loan_servicing_and_payment_dimensions_advance_independently
    """
    _, loan_id = _fresh_loan(api)

    after_ladder = _walk_the_delinquency_ladder(api, loan_id)
    a.assert_status(after_ladder, "DELINQUENT_90_PLUS", "payment_status")
    a.assert_status(after_ladder, "MASTER_SERVICING", "servicing_status")
    assert after_ladder["appraisal_required"] is True, (
        "reaching DELINQUENT_90_PLUS flags the asset for a fresh valuation"
    )


def test_the_servicing_transfer_moves_without_touching_the_payment_dimension(api):
    """The transfer consumes the auto-recorded event and leaves payment alone.

    The PRD: "Reaching `DELINQUENT_60` **auto-records a servicing transfer
    event** on the loan: its `event_code` is `MONETARY_DEFAULT_60D`, its
    `occurred_on` is the `as_of_date` from the request, its
    `days_delinquent_at_event` is 60, its `evidence_note` reads `auto-recorded on
    60-day monetary delinquency`, and its `recorded_by_user_id` is the calling
    `X-User-ID`."

    Design: Difficulty/non_linear_state_machine/loan_servicing_and_payment_dimensions_advance_independently
    """
    _, loan_id = _fresh_loan(api)
    _walk_the_delinquency_ladder(api, loan_id)

    transferred = fx.transfer_to_special_servicing(api, loan_id)
    a.assert_status(transferred, "SPECIAL_SERVICING", "servicing_status")
    a.assert_status(transferred, "DELINQUENT_90_PLUS", "payment_status")
    assert transferred["transfer_event_code"] == "MONETARY_DEFAULT_60D"
    assert transferred["transferred_to_special_on"].startswith("2026-08-01")
    assert transferred["asset_business_plan_due_date"].startswith("2026-09-30")

    events, _ = validate_paginated(
        api.list_loan_transfer_events(
            loan_id, MASTER_SERVICER, {"event_code": "MONETARY_DEFAULT_60D"}
        )
    )
    assert len(events) == 1, "the 60-day rung auto-records exactly one event"
    assert events[0]["triggers_transfer"] is True
    assert events[0]["consumed_by_transfer"] is True
    assert events[0]["days_delinquent_at_event"] == 60


def test_the_current_self_loop_increments_the_counter_three_times(api):
    """CURRENT to CURRENT is an observable edge, not an idempotent no-op.

    The PRD: "There is additionally a self-loop `CURRENT → CURRENT`, which
    requires `timely_payment_recorded` to be true and increases
    `consecutive_timely_payments` by one — this is how the three timely payments
    that a corrected loan needs are accumulated."

    Design: Difficulty/non_linear_state_machine/loan_servicing_and_payment_dimensions_advance_independently
    """
    _, loan_id = _fresh_loan(api)
    _walk_the_delinquency_ladder(api, loan_id)
    fx.transfer_to_special_servicing(api, loan_id)

    cured = validate_success(
        api.set_loan_payment_status(
            loan_id,
            {
                "to_status": "CURRENT",
                "as_of_date": "2026-10-10T00:00:00Z",
                "timely_payment_recorded": True,
            },
            MASTER_SERVICER,
        )
    )
    assert cured["consecutive_timely_payments"] == 1

    second = validate_success(
        api.set_loan_payment_status(
            loan_id,
            {
                "to_status": "CURRENT",
                "as_of_date": "2026-11-10T00:00:00Z",
                "timely_payment_recorded": True,
            },
            MASTER_SERVICER,
        )
    )
    assert second["consecutive_timely_payments"] == 2

    third = validate_success(
        api.set_loan_payment_status(
            loan_id,
            {
                "to_status": "CURRENT",
                "as_of_date": "2026-12-10T00:00:00Z",
                "timely_payment_recorded": True,
            },
            MASTER_SERVICER,
        )
    )
    assert third["consecutive_timely_payments"] == 3
    a.assert_status(third, "CURRENT", "payment_status")
    a.assert_status(third, "SPECIAL_SERVICING", "servicing_status")


# ==========================================================================
# The information-request cycle, capped at two round trips
# ==========================================================================
def _assumption_request_under_analysis(api):
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-I1"},
        loan_overrides={"loan_number": "L-I01"},
        event_factory=lambda client, loan_id: fx.record_transfer_event(
            client,
            loan_id,
            event_code="RECEIVERSHIP",
            occurred_on="2026-07-10T00:00:00Z",
            evidence_note="receiver appointed over the property",
            days_delinquent_at_event=None,
        ),
    )
    request = fx.submit_assumption_request(api, built["loan_id"])
    fx.set_request_status(api, request["id"], "UNDER_ANALYSIS")
    return built["loan_id"], request["id"]


def test_requesting_information_invalidates_the_analysis_already_recorded(api):
    """The first lap clears both analysis outputs back to null.

    The PRD: "From `UNDER_ANALYSIS` the manager may ask the borrower for more
    paperwork, `UNDER_ANALYSIS → INFO_REQUESTED`, which increases
    `info_request_count` by one and **invalidates any analysis already
    recorded**, clearing both `servicing_standard_margin_usd` and
    `servicing_standard_conclusion` back to null."

    Design: Difficulty/non_linear_state_machine/borrower_request_info_requested_cycle_capped_at_two_rounds
    """
    _, request_id = _assumption_request_under_analysis(api)

    analysed = fx.record_analysis(api, request_id)
    a.assert_money(
        analysed["servicing_standard_margin_usd"], 97500.00, "servicing_standard_margin_usd"
    )
    a.assert_status(analysed, "SERVICING_STANDARD_MET", "servicing_standard_conclusion")

    after_lap_one = fx.set_request_status(api, request_id, "INFO_REQUESTED")
    assert after_lap_one["info_request_count"] == 1
    a.assert_fields_null(
        after_lap_one, "servicing_standard_margin_usd", "servicing_standard_conclusion"
    )


def test_the_second_information_lap_is_permitted_and_closes_again(api):
    """Two laps are inside the cap and re-entry returns to UNDER_ANALYSIS.

    The PRD: "Returning from `INFO_REQUESTED` to `UNDER_ANALYSIS` closes the
    loop."

    Design: Difficulty/non_linear_state_machine/borrower_request_info_requested_cycle_capped_at_two_rounds
    """
    _, request_id = _assumption_request_under_analysis(api)

    fx.set_request_status(api, request_id, "INFO_REQUESTED")
    fx.set_request_status(api, request_id, "UNDER_ANALYSIS")
    second = fx.set_request_status(api, request_id, "INFO_REQUESTED")
    assert second["info_request_count"] == 2

    reopened = fx.set_request_status(api, request_id, "UNDER_ANALYSIS")
    a.assert_status(reopened, "UNDER_ANALYSIS")
    assert reopened["info_request_count"] == 2


def test_the_third_information_request_is_refused_and_leaves_no_trace(api):
    """The cap bites even though the transition itself is legal.

    The PRD: "The loop is capped at two round trips: an attempt to request
    information a third time, when `info_request_count` has already reached two,
    is refused with `ERR_INFO_REQUEST_LIMIT_EXCEEDED` even though the transition
    itself is otherwise legal."

    Design: Difficulty/non_linear_state_machine/borrower_request_info_requested_cycle_capped_at_two_rounds
    """
    _, request_id = _assumption_request_under_analysis(api)
    for _ in range(2):
        fx.set_request_status(api, request_id, "INFO_REQUESTED")
        fx.set_request_status(api, request_id, "UNDER_ANALYSIS")

    response = api.set_borrower_request_status(
        request_id, f.status_payload("INFO_REQUESTED"), ASSET_MANAGER
    )
    validate_error(response, e.ERR_INFO_REQUEST_LIMIT_EXCEEDED, 422)

    unchanged = validate_success(api.get_borrower_request(request_id, ASSET_MANAGER))
    a.assert_status(unchanged, "UNDER_ANALYSIS")
    assert unchanged["info_request_count"] == 2


# ==========================================================================
# The plan revision cycle, capped at three rounds
# ==========================================================================
def _plan_in_objected(api):
    """A trust, a loan and a plan carried to OBJECTED on a CONSENT_RIGHT."""
    built_loan = fx.loan_in_special_servicing(
        api,
        trust_overrides={"deal_name": "CMBS 2026-V1"},
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={"loan_number": "L-V01"},
        event_factory=fx.record_bankruptcy_event,
    )
    built = fx.scored_plan(
        api, built_loan["loan_id"], alternative_builders=[fx.add_modification_alternative]
    )
    scenario = {
        "trust_id": built_loan["trust_id"],
        "loan_id": built_loan["loan_id"],
        "plan_id": built["plan_id"],
        "alternative_id": built["alternative_ids"][0],
    }
    _object_to_the_plan(api, scenario)
    return scenario


def _object_to_the_plan(api, scenario):
    """Recommend, consult and obtain an objection, returning the consultation."""
    plan = validate_success(api.get_workout_plan(scenario["plan_id"], ASSET_MANAGER))
    if plan["status"] == "SCORED":
        fx.recommend_plan(api, scenario["plan_id"], plan["recommended_alternative_id"])
    consultation = fx.issue_plan_consultation(
        api, scenario["trust_id"], scenario["plan_id"]
    )
    a.assert_status(consultation, "CONSENT_RIGHT", "rights_type")
    fx.respond_to_consultation(
        api, consultation["id"], scenario["trust_id"], "OBJECTED"
    )
    return consultation


def test_each_revision_lap_resets_the_scoring_artefacts_and_climbs_the_counter(api):
    """OBJECTED to DRAFT nulls the plan's recommendation and the alternative's
    figures while revision_round increases.

    The PRD: "On revision, `revision_round` increases by one, the plan's
    `recommended_alternative_id`, `selected_alternative_id` and `scored_on` are
    all cleared to null, and every alternative in the plan whose status is
    `SCORED`, `SELECTED` or `DISCARDED` returns to `PROPOSED` with `rank`,
    `npv_usd` and `discounted_pv_usd` all cleared to null."

    Design: Difficulty/non_linear_state_machine/workout_plan_objection_revision_cycle_capped_at_three_rounds
    """
    scenario = _plan_in_objected(api)

    revised = validate_success(
        api.set_workout_plan_status(
            scenario["plan_id"], f.status_payload("DRAFT"), ASSET_MANAGER
        )
    )
    assert revised["revision_round"] == 1
    a.assert_fields_null(
        revised, "recommended_alternative_id", "selected_alternative_id", "scored_on"
    )

    alternative = validate_success(
        api.get_workout_alternative(scenario["alternative_id"], ASSET_MANAGER)
    )
    a.assert_status(alternative, "PROPOSED")
    a.assert_fields_null(alternative, "rank", "npv_usd", "discounted_pv_usd")


def test_rescoring_after_a_reset_reproduces_the_same_figures(api):
    """The reset is a genuine round trip: re-scoring recomputes from scratch.

    The PRD: "Re-scoring after a revision loop recomputes every `npv_usd` from
    scratch and may well recommend a different alternative."

    Design: Difficulty/non_linear_state_machine/workout_plan_objection_revision_cycle_capped_at_three_rounds
    """
    scenario = _plan_in_objected(api)
    validate_success(
        api.set_workout_plan_status(
            scenario["plan_id"], f.status_payload("DRAFT"), ASSET_MANAGER
        )
    )

    rescored = fx.score_plan(api, scenario["plan_id"])
    alternative = validate_success(
        api.get_workout_alternative(scenario["alternative_id"], ASSET_MANAGER)
    )
    a.assert_money(alternative["npv_usd"], NPV_MOD_NPV_CONTRACTUAL, "npv_usd")
    assert alternative["rank"] == 1
    assert rescored["recommended_alternative_id"] == scenario["alternative_id"]
    assert rescored["revision_round"] == 1


def test_the_fourth_revision_strands_the_plan_in_objected(api):
    """Three laps are permitted; the fourth is refused.

    The PRD: "`OBJECTED → DRAFT` is driven by the asset manager and is permitted
    while the plan's `revision_round` is below three; the fourth attempt is
    refused with `ERR_REVISION_LIMIT_EXCEEDED`, leaving abandonment as the only
    exit."

    Design: Difficulty/non_linear_state_machine/workout_plan_objection_revision_cycle_capped_at_three_rounds
    """
    scenario = _plan_in_objected(api)

    for expected_round in (1, 2, 3):
        revised = validate_success(
            api.set_workout_plan_status(
                scenario["plan_id"], f.status_payload("DRAFT"), ASSET_MANAGER
            )
        )
        assert revised["revision_round"] == expected_round
        fx.score_plan(api, scenario["plan_id"])
        _object_to_the_plan(api, scenario)

    response = api.set_workout_plan_status(
        scenario["plan_id"], f.status_payload("DRAFT"), ASSET_MANAGER
    )
    validate_error(response, e.ERR_REVISION_LIMIT_EXCEEDED, 422)

    stranded = validate_success(api.get_workout_plan(scenario["plan_id"], ASSET_MANAGER))
    a.assert_status(stranded, "OBJECTED")
    assert stranded["revision_round"] == 3


def test_an_abandoned_plan_remains_the_only_exit_from_a_stranded_revision(api):
    """Abandonment stays available from OBJECTED after the cap is reached.

    The PRD: "Abandonment is available from `DRAFT`, `SCORED`, `RECOMMENDED`,
    `CONSULTATION`, `OBJECTED`, `CONSENT_SATISFIED` or `APPROVED`."

    Design: Difficulty/non_linear_state_machine/workout_plan_objection_revision_cycle_capped_at_three_rounds
    """
    scenario = _plan_in_objected(api)
    for _ in range(3):
        validate_success(
            api.set_workout_plan_status(
                scenario["plan_id"], f.status_payload("DRAFT"), ASSET_MANAGER
            )
        )
        fx.score_plan(api, scenario["plan_id"])
        _object_to_the_plan(api, scenario)

    validate_error(
        api.set_workout_plan_status(
            scenario["plan_id"], f.status_payload("DRAFT"), ASSET_MANAGER
        ),
        e.ERR_REVISION_LIMIT_EXCEEDED,
        422,
    )
    abandoned = validate_success(
        api.set_workout_plan_status(
            scenario["plan_id"], f.status_payload("ABANDONED"), ASSET_MANAGER
        )
    )
    a.assert_status(abandoned, "ABANDONED")

    loan = validate_success(api.get_loan(scenario["loan_id"], COMMITTEE_OFFICER))
    a.assert_fields_null(loan, "active_workout_plan_id")
    a.assert_status(loan, "IN_WORKOUT", "servicing_status")
