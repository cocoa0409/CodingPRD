"""Exit transitions, closure cascades, and the Outcome Survey.

Queue-A transitive_cascade plus queue-B survey/error/state-machine corners.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    factories as f,
    fixtures as fx,
)

COORD = fx.COORD
SCREENER = fx.SCREENER
SPECIALIST = fx.SPECIALIST
SUPERVISOR = fx.SUPERVISOR


def test_flagged_check_cascades_to_child_waitlist(api):
    """PRD §3.1: "the moment any one screen reaches `FLAGGED`, the volunteer is
    driven `SCREENING → SCREENING_FAILED`, which is terminal; as a compensation
    cascade, any still-`OFFERED` proposal naming this volunteer is declined and
    the affected child is returned to the waitlist."

    Design: Difficulty/transitive_cascade/flagged_check_cascades_to_child_waitlist_depth4
    """
    fx.set_clock(fx.REF_CLOCK)
    vol = fx.create_volunteer(set_clock_first=False, full_name="V Flag",
                             home_zip="85001", interest_tags=["OUTDOORS"])
    # First screening cycle → ELIGIBLE.
    fx.submit_and_clear_screening(vol["id"], start_index=0)
    guardian = fx.create_guardian(consent_on_file=True, full_name="G Flag")
    child = fx.create_child(guardian["id"], first_name="Kai", age=13, home_zip="85001",
                           interest_tags=["OUTDOORS"])
    proposal = fx.propose_match(child["id"])
    # Re-screen (ELIGIBLE → SCREENING) creates checks at indices 3,4,5.
    validate_success(api.submit_screening(vol["id"], SCREENER), 200)
    crim, dmv, car = fx.screen_check_ids(vol["id"], start_index=3)
    validate_success(api.adjudicate_check(crim, f.adjudicate_payload("CLEAR", 0), SCREENER), 200)
    validate_success(api.adjudicate_check(dmv, f.adjudicate_payload("CLEAR", 0), SCREENER), 200)
    # FLAG the third check → cascade.
    flagged = validate_success(api.adjudicate_check(car, f.adjudicate_payload("FLAG", 2), SCREENER), 200)
    assert flagged["status"] == "FLAGGED"

    volunteer = validate_success(api.get_volunteer(vol["id"], SPECIALIST), 200)
    assert volunteer["status"] == "SCREENING_FAILED"
    prop = validate_success(api.get_proposal(proposal["id"], SPECIALIST), 200)
    assert prop["status"] == "DECLINED"
    child_now = validate_success(api.get_child(child["id"], SPECIALIST), 200)
    assert child_now["status"] == "WAITLISTED"


def test_flag_during_initial_screening_drives_screening_failed(api):
    """PRD §3.1: "Conversely, the moment any one screen reaches `FLAGGED`, the
    volunteer is driven `SCREENING → SCREENING_FAILED`, which is terminal".

    Design: Difficulty/transitive_cascade/flagged_check_cascades_to_child_waitlist_depth4
    """
    fx.set_clock(fx.REF_CLOCK)
    vol = fx.create_volunteer(set_clock_first=False, full_name="V Flag2",
                             home_zip="85001", interest_tags=["OUTDOORS"])
    validate_success(api.submit_screening(vol["id"], SCREENER), 200)
    crim, _dmv, _car = fx.screen_check_ids(vol["id"], start_index=0)
    flagged = validate_success(api.adjudicate_check(crim, f.adjudicate_payload("FLAG", 2), SCREENER), 200)
    assert flagged["status"] == "FLAGGED"
    volunteer = validate_success(api.get_volunteer(vol["id"], SPECIALIST), 200)
    assert volunteer["status"] == "SCREENING_FAILED"


def test_exit_finalize_closes_match_frees_volunteer_misses_contact(api):
    """PRD §3.7: "On a successful finalize, the exit moves `DRAFT → FINALIZED`
    and the match is closed — `relationship_status` becomes `CLOSED` and the
    match's `closure_reason` is set from the exit's `exit_type`. The closure
    cascades: every still-`OPEN` supervision follow-up on the match is swept to
    `MISSED` ... the volunteer returns `MATCHED → ELIGIBLE`".

    Design: Difficulty/transitive_cascade/exit_finalize_cascades_match_closed_volunteer_eligible_depth3
    """
    ctx = fx.setup_active_match(
        clock=fx.REF_CLOCK,
        volunteer_overrides={"full_name": "V Exit", "home_zip": "98101",
                             "interest_tags": ["COOKING"]},
        guardian_overrides={"full_name": "G Exit"},
        child_overrides={"first_name": "Ivy", "age": 10, "gender": "FEMALE",
                         "home_zip": "98101", "interest_tags": ["COOKING"],
                         "requires_same_gender": False},
        confirm_specialist_id="spec-7",
    )
    match_id = ctx["match"]["id"]
    sc_id = fx.first_open_contact_id(match_id)
    et = fx.open_exit(match_id, exit_type="EARLY_TERMINATION", initiated_by="AGENCY",
                      reason_code="SAFETY_CONCERN", specialist_headers=ctx["specialist_headers"])
    finalized = fx.finalize_exit(et["id"], supervisor_user_id="sup-9")
    assert finalized["status"] == "FINALIZED"

    match = validate_success(api.get_match(match_id, SUPERVISOR), 200)
    assert match["relationship_status"] == "CLOSED"
    assert match["closure_reason"] == "EARLY_TERMINATION"
    volunteer = validate_success(api.get_volunteer(ctx["volunteer"]["id"], SPECIALIST), 200)
    assert volunteer["status"] == "ELIGIBLE"
    contact = validate_success(api.get_supervision_contact(sc_id, SUPERVISOR), 200)
    assert contact["status"] == "MISSED"


def test_early_termination_finalize_returns_child_to_waitlist(api):
    """PRD §3.7: "the child's fate depends on the closure reason — an
    `EARLY_TERMINATION` returns the child `MATCHED → WAITLISTED` so the Little can
    be matched again".

    Design: Difficulty/transitive_cascade/exit_finalize_cascades_match_closed_volunteer_eligible_depth3
    """
    ctx = fx.setup_active_match(
        clock=fx.REF_CLOCK,
        volunteer_overrides={"full_name": "V Exit2", "home_zip": "98101",
                             "interest_tags": ["COOKING"]},
        guardian_overrides={"full_name": "G Exit2"},
        child_overrides={"first_name": "Ivy2", "age": 10, "gender": "FEMALE",
                         "home_zip": "98101", "interest_tags": ["COOKING"]},
        confirm_specialist_id="spec-7b",
    )
    child_id = ctx["child"]["id"]
    et = fx.open_exit(ctx["match"]["id"], exit_type="EARLY_TERMINATION",
                      initiated_by="AGENCY", reason_code="SAFETY_CONCERN",
                      specialist_headers=ctx["specialist_headers"])
    fx.finalize_exit(et["id"], supervisor_user_id="sup-9b")
    child = validate_success(api.get_child(child_id, SPECIALIST), 200)
    assert child["status"] == "WAITLISTED"


def test_outcome_survey_strong_band(api):
    """PRD §3.7: "a base equal to half the `relationship_quality` plus half the
    `child_outcome`, plus a rematch bonus of 0.5 when `would_rematch` is true ...
    stored as `composite_score`. ... `STRONG` when the score is at least 4.0".

    Design: Corner/calculations/outcome_composite_strong_band
    """
    ctx = fx.setup_closed_match(
        clock=fx.REF_CLOCK, exit_type="SUCCESSFUL_CLOSURE", reach_active=True,
        volunteer_overrides={"full_name": "V Os", "home_zip": "94105",
                             "interest_tags": ["STEM"]},
        guardian_overrides={"full_name": "G Os"},
        child_overrides={"first_name": "Os", "age": 12, "home_zip": "94105",
                         "interest_tags": ["STEM"]},
        confirm_specialist_id="spec-os", close_supervisor_id="sup-os",
    )
    resp = api.create_outcome_survey(
        f.outcome_survey_payload(ctx["match"]["id"], ctx["exit_transition"]["id"],
                                 relationship_quality=5, child_outcome=4, would_rematch=True),
        SUPERVISOR,
    )
    survey = validate_success(resp, 201)
    # 0.5*5 + 0.5*4 + 0.5 = 2.5 + 2.0 + 0.5 = 5.00
    assert survey["composite_score"] == 5.00
    assert survey["outcome_band"] == "STRONG"


def test_outcome_survey_already_exists_rejected(api):
    """PRD §3.7: "no prior survey exists for this `match_id` (otherwise
    `ERR_SURVEY_ALREADY_EXISTS`, HTTP 409)."

    Design: Corner/errors/survey_already_exists_on_second_submit
    """
    ctx = fx.setup_closed_match(
        clock=fx.REF_CLOCK, exit_type="SUCCESSFUL_CLOSURE", reach_active=True,
        volunteer_overrides={"full_name": "V Sa"},
        guardian_overrides={"full_name": "G Sa"},
        child_overrides={"first_name": "Sa"},
        confirm_specialist_id="spec-sa", close_supervisor_id="sup-sa",
    )
    fx.submit_survey(ctx["match"]["id"], ctx["exit_transition"]["id"],
                     relationship_quality=4, child_outcome=4, would_rematch=False)
    resp = api.create_outcome_survey(
        f.outcome_survey_payload(ctx["match"]["id"], ctx["exit_transition"]["id"],
                                 relationship_quality=3, child_outcome=3, would_rematch=False),
        SUPERVISOR,
    )
    validate_error(resp, ApiErrorId.ERR_SURVEY_ALREADY_EXISTS.value, 409)


def test_outcome_survey_not_required_on_early_termination_before_active(api):
    """PRD §3.7: "`survey_required` is computed and pinned: it is true exactly
    when the `exit_type` is `SUCCESSFUL_CLOSURE`, or when the match had reached
    `ACTIVE` at any point before the exit; otherwise it is false."
    PRD §3.7: "the referenced exit's `survey_required` is true (otherwise
    `ERR_SURVEY_NOT_REQUIRED`, HTTP 409)".

    Design: Corner/errors/survey_not_required_on_early_termination_before_active
    """
    # Match only INTRODUCED (held, never affirmed) and closed via EARLY_TERMINATION.
    ctx = fx.setup_closed_match(
        clock=fx.REF_CLOCK, exit_type="EARLY_TERMINATION", reach_active=False,
        volunteer_overrides={"full_name": "V Sn"},
        guardian_overrides={"full_name": "G Sn"},
        child_overrides={"first_name": "Sn"},
        confirm_specialist_id="spec-sn", close_supervisor_id="sup-sn",
    )
    et = validate_success(api.get_exit_transition(ctx["exit_transition"]["id"], SUPERVISOR), 200)
    assert et["survey_required"] is False
    resp = api.create_outcome_survey(
        f.outcome_survey_payload(ctx["match"]["id"], ctx["exit_transition"]["id"],
                                 relationship_quality=3, child_outcome=3, would_rematch=False),
        SUPERVISOR,
    )
    validate_error(resp, ApiErrorId.ERR_SURVEY_NOT_REQUIRED.value, 409)


def test_decline_already_declined_proposal_rejected(api):
    """PRD §2.6: "the state-machine precondition that the target resource is in a
    state from which the requested transition is defined, yielding
    `ERR_INVALID_STATE`".
    PRD §3.4: "it moves the proposal `OFFERED → DECLINED` and bubbles the child
    `PROPOSED → WAITLISTED`, clearing the child's `open_proposal_id`."

    Design: Corner/state_machines/decline_already_declined_proposal_returns_invalid_state
    """
    fx.set_clock(fx.REF_CLOCK)
    fx.create_eligible_volunteer(set_clock_first=False, full_name="V Dd")
    guardian = fx.create_guardian(consent_on_file=True, full_name="G Dd")
    child = fx.create_child(guardian["id"], first_name="Dd")
    proposal = fx.propose_match(child["id"])
    validate_success(
        api.decline_proposal(proposal["id"], {"decline_reason": "POOR_FIT"}, SPECIALIST), 200
    )
    resp = api.decline_proposal(proposal["id"], {"decline_reason": "POOR_FIT"}, SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
