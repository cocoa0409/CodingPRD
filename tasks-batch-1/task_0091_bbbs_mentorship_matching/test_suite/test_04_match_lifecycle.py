"""Match confirmation gates, the parallel relationship/compliance axes, the
meeting affirm-vs-rescind branch, and the per-volunteer active-match invariant.

Queue-A non_linear_state_machine / cross_entity / compensating-invariant plus
queue-B state-machine precondition corners.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    fixtures as fx,
)

SPECIALIST = fx.SPECIALIST
SUPERVISOR = fx.SUPERVISOR


def test_accept_requires_volunteer_eligible(api):
    """PRD §3.4: "The selected volunteer must still be `ELIGIBLE`, failing which
    the accept is rejected with `ERR_VOLUNTEER_NOT_ELIGIBLE` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/accept_proposal_requires_volunteer_eligible
    """
    fx.set_clock(fx.REF_CLOCK)
    vol = fx.create_eligible_volunteer(set_clock_first=False, full_name="V Ce1",
                                      home_zip="30301", interest_tags=["ARTS"])
    guardian = fx.create_guardian(consent_on_file=True, full_name="G Ce1")
    child = fx.create_child(guardian["id"], first_name="Ada", gender="FEMALE",
                           home_zip="30301", interest_tags=["ARTS"])
    proposal = fx.propose_match(child["id"])
    # Deactivate the selected volunteer (ELIGIBLE → INACTIVE) while proposal stays OFFERED.
    deact = validate_success(api.deactivate_volunteer(vol["id"], SPECIALIST), 200)
    assert deact["status"] == "INACTIVE"
    current = validate_success(api.get_volunteer(vol["id"], SPECIALIST), 200)["version"]
    resp = api.accept_proposal(
        proposal["id"], {"expected_volunteer_version": current}, SPECIALIST
    )
    validate_error(resp, ApiErrorId.ERR_VOLUNTEER_NOT_ELIGIBLE.value, 409)


def test_accept_rejected_for_ineligible_volunteer_leaves_proposal_offered(api):
    """PRD §3.4: "The selected volunteer must still be `ELIGIBLE`, failing which
    the accept is rejected with `ERR_VOLUNTEER_NOT_ELIGIBLE` (HTTP 409)".
    PRD §3.4: "On success the proposal becomes `ACCEPTED`" (so a rejected accept
    leaves it `OFFERED`).

    Design: Difficulty/cross_entity_state_dependency/accept_proposal_requires_volunteer_eligible
    """
    fx.set_clock(fx.REF_CLOCK)
    vol = fx.create_eligible_volunteer(set_clock_first=False, full_name="V Ce1b",
                                      home_zip="30301", interest_tags=["ARTS"])
    guardian = fx.create_guardian(consent_on_file=True, full_name="G Ce1b")
    child = fx.create_child(guardian["id"], first_name="Ada2", gender="FEMALE",
                           home_zip="30301", interest_tags=["ARTS"])
    proposal = fx.propose_match(child["id"])
    validate_success(api.deactivate_volunteer(vol["id"], SPECIALIST), 200)
    current = validate_success(api.get_volunteer(vol["id"], SPECIALIST), 200)["version"]
    resp = api.accept_proposal(
        proposal["id"], {"expected_volunteer_version": current}, SPECIALIST
    )
    validate_error(resp, ApiErrorId.ERR_VOLUNTEER_NOT_ELIGIBLE.value, 409)
    prop = validate_success(api.get_proposal(proposal["id"], SPECIALIST), 200)
    assert prop["status"] == "OFFERED", "rejected accept must not advance the proposal"


def test_match_relationship_active_while_compliance_turns_amber(api):
    """PRD §3.6: "the posture is `AMBER` if the days since contact exceed 30, or
    the days since activity exceed 45."
    PRD §3.5: "Affirming a held meeting — permitted only while it is `HELD` —
    moves it `HELD → AFFIRMED` and advances the parent match `INTRODUCED →
    ACTIVE`".

    Design: Difficulty/non_linear_state_machine/match_parallel_relationship_and_compliance_axes
    """
    ctx = fx.setup_active_match(
        clock=fx.REF_CLOCK,
        volunteer_overrides={"full_name": "V Par", "home_zip": "60601",
                             "interest_tags": ["STEM"]},
        guardian_overrides={"full_name": "G Par"},
        child_overrides={"first_name": "Eli", "age": 12, "home_zip": "60601",
                         "interest_tags": ["STEM"]},
    )
    match_id = ctx["match"]["id"]
    # Affirm happened at the meeting time 2026-01-02; advance 40 days with no new contact.
    fx.set_clock("2026-02-11T00:00:00Z")
    match = validate_success(api.get_match(match_id, SUPERVISOR), 200)
    assert match["relationship_status"] == "ACTIVE"
    assert match["compliance_status"] == "AMBER"


def test_match_active_axis_is_green_at_activation(api):
    """PRD §3.5: "Affirming a held meeting — permitted only while it is `HELD` —
    moves it `HELD → AFFIRMED` and advances the parent match `INTRODUCED →
    ACTIVE`, stamping the match's `activated_at` with the current instant and
    opening the first supervision follow-up (in `OPEN`) whose `due_at` is the
    activation instant plus thirty days."
    PRD §3.6: "Otherwise the posture is `GREEN`."

    Design: Difficulty/non_linear_state_machine/match_parallel_relationship_and_compliance_axes
    """
    ctx = fx.setup_active_match(
        clock=fx.REF_CLOCK,
        volunteer_overrides={"full_name": "V Par2", "home_zip": "60601",
                             "interest_tags": ["STEM"]},
        guardian_overrides={"full_name": "G Par2"},
        child_overrides={"first_name": "Eli2", "age": 12, "home_zip": "60601",
                         "interest_tags": ["STEM"]},
    )
    # Read on the same day as activation: relationship ACTIVE, compliance GREEN.
    fx.set_clock("2026-01-02T12:00:00Z")
    match = validate_success(api.get_match(ctx["match"]["id"], SUPERVISOR), 200)
    assert match["relationship_status"] == "ACTIVE"
    assert match["compliance_status"] == "GREEN"


def test_held_meeting_rescind_keeps_match_introduced_no_contact(api):
    """PRD §3.5: "Rescinding a held meeting — also permitted only while it is
    `HELD` — instead moves it `HELD → RESCINDED`, leaving the parent match in
    `INTRODUCED` so that a fresh meeting may be scheduled."

    Design: Difficulty/non_linear_state_machine/meeting_held_branches_affirm_vs_rescind
    """
    ctx = fx.setup_introduced_match(
        clock=fx.REF_CLOCK,
        volunteer_overrides={"full_name": "V Br", "gender": "FEMALE",
                             "home_zip": "73301", "interest_tags": ["READING"]},
        guardian_overrides={"full_name": "G Br"},
        child_overrides={"first_name": "Zoe", "age": 7, "gender": "FEMALE",
                         "home_zip": "73301", "interest_tags": ["READING"]},
    )
    meeting_id = ctx["meeting"]["id"]
    match_id = ctx["match"]["id"]
    spec = ctx["specialist_headers"]
    resp = api.rescind_meeting(meeting_id, spec)
    rescinded = validate_success(resp, 200)
    assert rescinded["status"] == "RESCINDED"
    match = validate_success(api.get_match(match_id, spec), 200)
    assert match["relationship_status"] == "INTRODUCED"
    # Rescind opens no SupervisionContact.
    contacts, meta = validate_paginated(api.list_match_supervision_contacts(match_id, SUPERVISOR))
    assert meta["total_count"] == 0


def test_held_meeting_affirm_branch_activates_and_opens_contact(api):
    """PRD §3.5: "Affirming a held meeting — permitted only while it is `HELD` —
    moves it `HELD → AFFIRMED` and advances the parent match `INTRODUCED →
    ACTIVE`, stamping the match's `activated_at` with the current instant and
    opening the first supervision follow-up (in `OPEN`)".

    Design: Difficulty/non_linear_state_machine/meeting_held_branches_affirm_vs_rescind
    """
    ctx = fx.setup_introduced_match(
        clock=fx.REF_CLOCK,
        volunteer_overrides={"full_name": "V Br2", "gender": "FEMALE",
                             "home_zip": "73301", "interest_tags": ["READING"]},
        guardian_overrides={"full_name": "G Br2"},
        child_overrides={"first_name": "Zoe2", "age": 7, "gender": "FEMALE",
                         "home_zip": "73301", "interest_tags": ["READING"]},
    )
    meeting_id = ctx["meeting"]["id"]
    match_id = ctx["match"]["id"]
    spec = ctx["specialist_headers"]
    affirmed = validate_success(api.affirm_meeting(meeting_id, spec), 200)
    assert affirmed["status"] == "AFFIRMED"
    match = validate_success(api.get_match(match_id, spec), 200)
    assert match["relationship_status"] == "ACTIVE"
    assert match["activated_at"] is not None
    # Affirm (unlike rescind) opens the first supervision follow-up.
    _contacts, meta = validate_paginated(api.list_match_supervision_contacts(match_id, SUPERVISOR))
    assert meta["total_count"] == 1


def test_hold_second_meeting_when_match_not_confirmed_rejected(api):
    """PRD §3.5: "Holding the meeting is permitted only when the meeting is
    `SCHEDULED` and its parent match is in `CONFIRMED`; if the parent match is
    not in `CONFIRMED`, the hold is rejected with `ERR_MATCH_NOT_READY_FOR_MEETING`
    (HTTP 409)."

    Design: Corner/state_machines/hold_meeting_when_match_not_confirmed_returns_invalid_state
    """
    ctx = fx.setup_introduced_match(
        clock=fx.REF_CLOCK,
        volunteer_overrides={"full_name": "V Hm", "home_zip": "60601",
                             "interest_tags": ["STEM"]},
        guardian_overrides={"full_name": "G Hm"},
        child_overrides={"first_name": "Hmm", "home_zip": "60601",
                         "interest_tags": ["STEM"]},
        meeting_start="2026-01-05T10:00:00Z", meeting_end="2026-01-05T11:00:00Z",
    )
    match_id = ctx["match"]["id"]
    spec = ctx["specialist_headers"]
    # Match is now INTRODUCED (first meeting HELD). Schedule + try to hold a 2nd.
    mtg2 = fx.schedule_meeting(match_id, "2026-01-06T10:00:00Z", "2026-01-06T11:00:00Z",
                              location="M2", specialist_headers=spec)
    resp = api.hold_meeting(mtg2["id"], {}, spec)
    validate_error(resp, ApiErrorId.ERR_MATCH_NOT_READY_FOR_MEETING.value, 409)


def test_volunteer_active_match_count_conserved_across_accept_and_finalize(api):
    """PRD §3.4: "the volunteer advances `ELIGIBLE → MATCHED` with its
    `active_match_count` incremented to 1".
    PRD §3.7: "the volunteer returns `MATCHED → ELIGIBLE` (its `active_match_count`
    dropping back to 0, which frees the Big to be re-matched)".

    Design: Difficulty/compensating_invariant/volunteer_active_match_count_conserved_across_accept_finalize
    """
    ctx = fx.setup_active_match(
        clock=fx.REF_CLOCK,
        volunteer_overrides={"full_name": "V Inv1", "home_zip": "94105",
                             "interest_tags": ["STEM"]},
        guardian_overrides={"full_name": "G Inv1"},
        child_overrides={"first_name": "Max", "age": 12, "home_zip": "94105",
                         "interest_tags": ["STEM"]},
        confirm_specialist_id="spec-A",
    )
    vol_id = ctx["volunteer"]["id"]
    after_accept = validate_success(api.get_volunteer(vol_id, SPECIALIST), 200)
    assert after_accept["active_match_count"] == 1

    et = fx.open_exit(ctx["match"]["id"], exit_type="SUCCESSFUL_CLOSURE",
                      reason_code="GRADUATION", specialist_headers=ctx["specialist_headers"])
    fx.finalize_exit(et["id"], supervisor_user_id="sup-B")
    after_close = validate_success(api.get_volunteer(vol_id, SPECIALIST), 200)
    assert after_close["active_match_count"] == 0
    assert after_close["status"] == "ELIGIBLE"


def test_volunteer_status_returns_to_eligible_after_successful_closure(api):
    """PRD §3.4: "the volunteer advances `ELIGIBLE → MATCHED`".
    PRD §3.7: "the volunteer returns `MATCHED → ELIGIBLE` (its `active_match_count`
    dropping back to 0, which frees the Big to be re-matched)".

    Design: Difficulty/compensating_invariant/volunteer_active_match_count_conserved_across_accept_finalize
    """
    ctx = fx.setup_active_match(
        clock=fx.REF_CLOCK,
        volunteer_overrides={"full_name": "V Inv1b", "home_zip": "94105",
                             "interest_tags": ["STEM"]},
        guardian_overrides={"full_name": "G Inv1b"},
        child_overrides={"first_name": "Max2", "age": 12, "home_zip": "94105",
                         "interest_tags": ["STEM"]},
        confirm_specialist_id="spec-A2",
    )
    vol_id = ctx["volunteer"]["id"]
    matched = validate_success(api.get_volunteer(vol_id, SPECIALIST), 200)
    assert matched["status"] == "MATCHED"
    et = fx.open_exit(ctx["match"]["id"], exit_type="SUCCESSFUL_CLOSURE",
                      reason_code="GRADUATION", specialist_headers=ctx["specialist_headers"])
    fx.finalize_exit(et["id"], supervisor_user_id="sup-B2")
    freed = validate_success(api.get_volunteer(vol_id, SPECIALIST), 200)
    assert freed["status"] == "ELIGIBLE"
    assert freed["active_match_count"] == 0
