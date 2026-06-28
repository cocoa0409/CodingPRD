"""Advancement: requirement sign-off, the cyclic revision loop, approval gates."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_leader_headers,
    make_registrar_headers,
    create_council_and_troop,
    create_member,
    create_registered_youth,
    setup_registered_youth_with_advancement,
    setup_submitted_advancement,
    sign_all_requirements,
    create_advancement_payload,
)

REG = TEST_USERS["registrar_headers"]
LEAD = TEST_USERS["leader_headers"]
LEADER_BOB = make_leader_headers("leader-bob")
REGISTRAR_AMY = make_registrar_headers("registrar-amy")


def test_advancement_submitted_returned_resubmit_approve_cycle(api):
    """PRD §3.5: "From RETURNED the leader may submit again — permitted only when
    requirements_signed still equals requirements_total — which moves it back to
    SUBMITTED and re-stamps submitted_by_user_id with the resubmitting operator's id."
    PRD §3.5: "Approving a submitted advancement moves it from SUBMITTED to the
    terminal APPROVED ... When an approved advancement is of kind RANK, the member's
    rank is advanced to the advancement's target."

    Design: Difficulty/non_linear_state_machine/advancement_submitted_returned_resubmit_cycle
    """
    council, troop, member, adv = setup_submitted_advancement(
        requirements_total=2, submitter_id="leader-bob", target="TENDERFOOT", kind="RANK"
    )
    get_success_data(api.return_advancement(adv["id"], REG))

    # RETURNED -> SUBMITTED (resubmit), then SUBMITTED -> APPROVED.
    resubmitted = validate_success(api.submit_advancement(adv["id"], LEADER_BOB), 200)
    assert resubmitted["status"] == "SUBMITTED"
    approved = validate_success(api.approve_advancement(adv["id"], REGISTRAR_AMY), 200)

    assert approved["status"] == "APPROVED"
    member_after = validate_success(api.get_member(member["id"], REG), 200)
    assert member_after["rank"] == "TENDERFOOT"


def test_advancement_rank_approval_advances_member_rank(api):
    """PRD §3.5: "When an approved advancement is of kind RANK, the member's rank is
    advanced to the advancement's target; a badge approval leaves the rank
    untouched."

    Design: Difficulty/non_linear_state_machine/advancement_submitted_returned_resubmit_cycle
    """
    council, troop, member, adv = setup_submitted_advancement(
        requirements_total=2, submitter_id="leader-bob", target="TENDERFOOT", kind="RANK"
    )
    approved = validate_success(api.approve_advancement(adv["id"], REGISTRAR_AMY), 200)
    assert approved["status"] == "APPROVED"
    member_after = validate_success(api.get_member(member["id"], REG), 200)
    assert member_after["rank"] == "TENDERFOOT"


def test_completion_pct_recomputed_on_sign(api):
    """PRD §3.5: "Each requirement sign-off increases requirements_signed by one,
    capped so it never exceeds requirements_total, and recomputes completion_pct as
    the signed count divided by the total count, multiplied by one hundred, rounded
    half-up to two decimal places."

    Design: Corner/calculations/completion_pct_recomputed_on_sign
    """
    council, troop = create_council_and_troop(
        council_overrides={"name": "K3"}, troop_overrides={"unit_number": "K-3"}
    )
    member = create_member(troop["id"], member_type="YOUTH", full_name="Adv Y")
    adv = get_success_data(
        api.create_advancement(
            member["id"],
            create_advancement_payload(kind="BADGE", target="FIRST_AID", requirements_total=4, badge_code="FA-01"),
            LEAD,
        )
    )
    signed = validate_success(api.sign_requirement(adv["id"], LEAD), 200)
    assert signed["requirements_signed"] == 1
    assert signed["completion_pct"] == 25.0


def test_submit_advancement_requirements_incomplete_rejected(api):
    """PRD §3.5: "A premature submit is rejected with ERR_REQUIREMENTS_INCOMPLETE."

    Design: Corner/validations/submit_advancement_requirements_incomplete
    """
    council, troop, member, adv = setup_registered_youth_with_advancement(
        adv_overrides={"kind": "RANK", "target": "TENDERFOOT", "requirements_total": 2},
        council_overrides={"name": "V4"},
    )
    resp = api.submit_advancement(adv["id"], LEADER_BOB)
    validate_error(resp, ApiErrorId.ERR_REQUIREMENTS_INCOMPLETE.value)


def test_approve_returned_advancement_state_beats_segregation(api):
    """PRD §3.9: "then the state-machine precondition that the target be in a state
    from which the transition is defined (ERR_INVALID_STATE) ... After those come
    the business-safety checks: segregation of duties on background-check resolution
    and advancement approval (ERR_SEGREGATION_OF_DUTIES)."
    PRD §3.5: "Approving a submitted advancement moves it from SUBMITTED to the
    terminal APPROVED."

    Design: Difficulty/priority_pair_validation_conflict/approve_state_beats_segregation_conflict
    """
    council, troop, member, adv = setup_submitted_advancement(
        requirements_total=1, submitter_id="leader-bob", council_overrides={"name": "P5"}
    )
    # Return it so it is RETURNED (not SUBMITTED) -> state check applies; the
    # approver (a CouncilRegistrar, the only role that may approve per PRD §3.6)
    # carries the same operator id as the submitter (leader-bob) -> segregation
    # would also apply, but the state precedence (lower priority number per
    # PRD §3.9) wins, so ERR_INVALID_STATE is reported.
    get_success_data(api.return_advancement(adv["id"], REG))
    resp = api.approve_advancement(adv["id"], make_registrar_headers("leader-bob"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_approve_returned_advancement_reports_invalid_state_not_segregation(api):
    """PRD §3.9: "they are evaluated in a fixed priority order so that the earliest
    applicable failure is the one reported ... then the state-machine precondition
    that the target be in a state from which the transition is defined
    (ERR_INVALID_STATE)."

    Design: Difficulty/priority_pair_validation_conflict/approve_state_beats_segregation_conflict
    """
    council, troop, member, adv = setup_submitted_advancement(
        requirements_total=1, submitter_id="leader-bob", council_overrides={"name": "P5b"}
    )
    get_success_data(api.return_advancement(adv["id"], REG))
    # Approve is owned by CouncilRegistrar (PRD §3.6); reuse the submitter's
    # operator id so segregation would also fire — but the earliest-applicable
    # failure is the state precondition, never the segregation check (PRD §3.9).
    resp = api.approve_advancement(adv["id"], make_registrar_headers("leader-bob"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_approve_suspended_member_requires_registered(api):
    """PRD §3.5: "the member must currently be REGISTERED (an approval against a
    non-registered member is rejected with ERR_MEMBER_NOT_REGISTERED)."

    Design: Difficulty/cross_entity_state_dependency/advancement_approve_requires_member_registered
    """
    council, troop, member, adv = setup_submitted_advancement(
        requirements_total=1, submitter_id="leader-bob", council_overrides={"name": "X7"}
    )
    # Suspend the member so the otherwise-valid approve is gated by member state.
    get_success_data(api.suspend_member(member["id"], LEAD))

    resp = api.approve_advancement(adv["id"], REGISTRAR_AMY)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_REGISTERED.value)

    adv_after = validate_success(api.get_advancement(adv["id"], REG), 200)
    assert adv_after["status"] == "SUBMITTED"


def test_approve_suspended_member_leaves_advancement_submitted(api):
    """PRD §3.5: "Approving a submitted advancement moves it from SUBMITTED to the
    terminal APPROVED, but is gated by two conditions beyond the state itself ...
    and the member must currently be REGISTERED (an approval against a non-registered
    member is rejected with ERR_MEMBER_NOT_REGISTERED)."

    Design: Difficulty/cross_entity_state_dependency/advancement_approve_requires_member_registered
    """
    council, troop, member, adv = setup_submitted_advancement(
        requirements_total=1, submitter_id="leader-bob", council_overrides={"name": "X7b"}
    )
    get_success_data(api.suspend_member(member["id"], LEAD))
    resp = api.approve_advancement(adv["id"], REGISTRAR_AMY)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_REGISTERED.value)
    adv_after = validate_success(api.get_advancement(adv["id"], REG), 200)
    assert adv_after["status"] == "SUBMITTED"
