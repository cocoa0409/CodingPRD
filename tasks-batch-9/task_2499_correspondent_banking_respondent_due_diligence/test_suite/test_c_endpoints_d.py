"""Corner queue - section endpoints, part D: conditional actions with their own gates."""
from test_helpers import (
    ApiErrorId,
    OFFICER_ID,
    add_control_rows,
    add_nested,
    adjudicate_nested,
    approve_plan,
    assert_instant_equals,
    corridor,
    draft_plan,
    licensed_respondent,
    new_jurisdiction,
    open_profile,
    open_questionnaire,
    overlay_row,
    progress_plan,
    read_nested,
    read_plan,
    read_respondent,
    return_questionnaire,
    set_clock,
    setup_approved_respondent,
    submit_plan,
    submit_questionnaire,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ANALYST, OFFICER, RM


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def test_prohibiting_a_nested_relationship_restricts_the_whole_respondent(api):
    """Prohibition is the one nested action that reaches back into the parent, and because a
    prohibited row weighs nothing the exposure rollup collapses in the same request.

    Design: Corner/endpoints/prohibiting_a_nested_relationship_restricts_the_whole_respondent
    """
    _de()
    france = new_jurisdiction(
        jurisdiction_code="FR", name="France", basel_aml_index=5.0, corridor_risk_weight=1.2
    )
    bundle = setup_approved_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
        nested_activity_permitted=True,
    )
    rid = bundle["respondent"]["id"]
    row = add_nested(
        rid, "FR", downstream_institution_name="Banque Aval", discovery_source="QUESTIONNAIRE"
    )
    assert row["state"] == "DISCLOSED"
    assert read_respondent(rid)["nested_exposure_units"] == 1
    validate_success(
        api.amend_jurisdiction_profile(
            france["id"], {"nested_correspondent_prohibited": True}, OFFICER
        )
    )

    prohibited = adjudicate_nested(row["id"], "PROHIBIT", OFFICER)

    assert prohibited["state"] == "PROHIBITED"
    assert prohibited["prohibition_reason"] == "JURISDICTION_PROHIBITS_NESTING"
    assert prohibited["adjudicated_by_user_id"] == OFFICER_ID
    assert_instant_equals(prohibited["adjudicated_at"], "2026-08-01T00:00:00Z")
    assert read_nested(row["id"])["state"] == "PROHIBITED"

    respondent = read_respondent(rid)
    assert respondent["dd_state"] == "RESTRICTED"
    assert respondent["restriction_reason"] == "PROHIBITED_NESTING"
    assert respondent["payment_posture"] == "BLOCKED"
    assert respondent["nested_exposure_units"] == 0
    assert respondent["disclosed_nested_count"] == 0
    assert respondent["max_nested_depth"] == 0


def test_questionnaire_return_is_allowed_three_times_then_refused(api):
    """The round counter is a hard ceiling rather than a wrap-around: the return that takes it
    from two to three still succeeds and the next one is refused outright.

    Design: Corner/endpoints/questionnaire_return_is_allowed_three_times_then_refused
    """
    _de()
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = respondent["id"]
    questionnaire = open_questionnaire(rid)
    rows = add_control_rows(questionnaire["id"], rid)

    returned = None
    for _ in range(3):
        submit_questionnaire(questionnaire["id"], rid)
        overlay_row(rows["GOVERNANCE"]["id"], gap_severity="MAJOR")
        returned = return_questionnaire(
            questionnaire["id"], clarification_note="Please expand on governance."
        )
    assert returned["clarification_rounds"] == 3
    assert returned["state"] == "RETURNED_FOR_CLARIFICATION"

    submit_questionnaire(questionnaire["id"], rid)
    under_assessment = overlay_row(rows["GOVERNANCE"]["id"], gap_severity="MAJOR")
    assert under_assessment["id"] == rows["GOVERNANCE"]["id"]

    response = api.decide_assessment(
        questionnaire["id"],
        {"action": "RETURN", "clarification_note": "Round four questions"},
        ANALYST,
    )
    validate_error(response, ApiErrorId.ERR_ROUNDS_EXHAUSTED, expected_status=409)

    stored = validate_success(api.get_questionnaire(questionnaire["id"], ANALYST))
    assert stored["clarification_rounds"] == 3
    assert stored["state"] == "UNDER_ASSESSMENT"


def test_closing_a_plan_requires_both_the_elapsed_notice_and_a_settled_obligation(api):
    """Two independent gates guard the same action, so the refusals arrive in order: first the
    notice period, then - at the very instant it elapses - the unsettled obligation.

    Design: Corner/endpoints/closing_a_plan_requires_both_the_elapsed_notice_and_a_settled_obligation
    """
    _de()
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = respondent["id"]
    open_profile(rid, [corridor("DE", 400000.00, 80)])
    plan = draft_plan(
        rid, RM, termination_reason="COMMERCIAL", cap_basis="FORWARD_PROJECTED",
        original_obligation_cents=1000,
    )
    assert plan["notice_period_days"] == 105
    submit_plan(plan["id"])
    approve_plan(plan["id"])
    served = progress_plan(plan["id"], "SERVE_NOTICE")
    assert_instant_equals(served["notice_served_at"], "2026-08-01T00:00:00Z")
    assert_instant_equals(served["wind_down_end_at"], "2026-11-14T00:00:00Z")
    assert progress_plan(plan["id"], "BEGIN_WIND_DOWN")["state"] == "WIND_DOWN"

    too_early = api.progress_closure_plan(plan["id"], {"action": "CLOSE"}, RM)
    validate_error(
        too_early, ApiErrorId.ERR_NOTICE_PERIOD_NOT_ELAPSED, expected_status=422
    )

    set_clock("2026-11-14T00:00:00Z")
    unsettled = api.progress_closure_plan(plan["id"], {"action": "CLOSE"}, RM)
    validate_error(unsettled, ApiErrorId.ERR_OBLIGATION_OUTSTANDING, expected_status=422)

    allocated = validate_success(
        api.allocate_settlement(
            plan["id"], {"action": "ALLOCATE", "amount_cents": 1000}, RM
        )
    )
    assert allocated["outstanding_obligation_cents"] == 0
    assert allocated["settled_cents"] == 1000

    closed = validate_success(api.progress_closure_plan(plan["id"], {"action": "CLOSE"}, RM))
    assert closed["state"] == "CLOSED"
    assert_instant_equals(closed["closed_at"], "2026-11-14T00:00:00Z")
    assert read_plan(plan["id"])["state"] == "CLOSED"

    terminated = read_respondent(rid)
    assert terminated["dd_state"] == "TERMINATED"
    assert terminated["payment_posture"] == "BLOCKED"
