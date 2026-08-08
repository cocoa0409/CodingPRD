"""Disqualification proposal, ADH referral, hearing fork, and segregation of duties."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_substantiated_case,
    add_proposed_disqualification,
    add_adh_referred_disqualification,
    setup_held_hearing,
    setup_imposed_disqualification,
    add_decided_ipv_hearing,
    create_disqualification_payload,
    create_hearing_payload,
    decide_hearing_payload,
    make_adjudicator_headers,
    assert_hearing,
    assert_disqualification,
)

ADJUDICATOR = TEST_USERS["adjudicator_headers"]
INVESTIGATOR = TEST_USERS["investigator_headers"]


# --------------------------------------------------------------------------- #
# Hearing fork from HELD
# --------------------------------------------------------------------------- #
def test_hearing_ipv_branch_imposes_disqualification(api):
    """PRD 3.5: "An `outcome` of `IPV` advances the hearing to `DECIDED_IPV`, sets
    `outcome` to `IPV`, and imposes the linked disqualification."

    Design: Difficulty/non_linear_state_machine/hearing_fork_ipv_branch
    """
    ctx = setup_held_hearing(api)
    resp = api.decide_hearing(ctx["hearing"]["id"], decide_hearing_payload("IPV"), ADJUDICATOR)
    data = validate_success(resp)
    assert_hearing(data)
    assert data["status"] == "DECIDED_IPV", f"expected DECIDED_IPV, got {data['status']}"
    assert data["outcome"] == "IPV", f"expected outcome IPV, got {data['outcome']}"
    disq = validate_success(api.get_disqualification(ctx["disqualification"]["id"], ADJUDICATOR))
    assert disq["status"] == "IMPOSED", f"expected disqualification IMPOSED, got {disq['status']}"


def test_hearing_no_ipv_branch_declines_disqualification(api):
    """PRD 3.5: "An `outcome` of `NO_IPV` advances the hearing to `DECIDED_NO_IPV`, and an
    `outcome` of `DISMISSED` advances it to `DISMISSED`; both of these set the corresponding
    `outcome`, and both decline the linked disqualification — moving it from `ADH_REFERRED`
    to `DECLINED` with no penalty and no change to the subject or any overpayment."

    Design: Difficulty/non_linear_state_machine/hearing_fork_ipv_branch
    """
    ctx = setup_held_hearing(api)
    resp = api.decide_hearing(ctx["hearing"]["id"], decide_hearing_payload("NO_IPV"), ADJUDICATOR)
    data = validate_success(resp)
    assert data["status"] == "DECIDED_NO_IPV", f"expected DECIDED_NO_IPV, got {data['status']}"
    disq = validate_success(api.get_disqualification(ctx["disqualification"]["id"], ADJUDICATOR))
    assert disq["status"] == "DECLINED", f"expected DECLINED, got {disq['status']}"
    subj = validate_success(api.get_subject(ctx["subject"]["id"], ADJUDICATOR))
    assert subj["prior_ipv_count"] == 0, (
        f"NO_IPV must not change the subject, got prior_ipv_count {subj['prior_ipv_count']}"
    )


def test_hearing_dismissed_branch_declines_disqualification(api):
    """PRD 3.5: "An `outcome` of `NO_IPV` advances the hearing to `DECIDED_NO_IPV`, and an
    `outcome` of `DISMISSED` advances it to `DISMISSED`; both of these set the corresponding
    `outcome`, and both decline the linked disqualification — moving it from `ADH_REFERRED`
    to `DECLINED` with no penalty and no change to the subject or any overpayment."

    Design: Difficulty/non_linear_state_machine/hearing_fork_ipv_branch
    """
    ctx = setup_held_hearing(api)
    resp = api.decide_hearing(ctx["hearing"]["id"], decide_hearing_payload("DISMISSED"), ADJUDICATOR)
    data = validate_success(resp)
    assert data["status"] == "DISMISSED", f"expected DISMISSED, got {data['status']}"
    disq = validate_success(api.get_disqualification(ctx["disqualification"]["id"], ADJUDICATOR))
    assert disq["status"] == "DECLINED", f"expected DECLINED, got {disq['status']}"


# --------------------------------------------------------------------------- #
# Scheduling requires ADH_REFERRED
# --------------------------------------------------------------------------- #
def test_schedule_hearing_requires_adh_referred(api):
    """PRD 3.5: "Scheduling against a disqualification that is not in `ADH_REFERRED` is
    rejected with `ERR_ADH_NOT_REFERRED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/schedule_hearing_requires_adh_referred
    """
    ctx = create_substantiated_case(api)
    add_proposed_disqualification(api, ctx)  # still PROPOSED, not referred
    resp = api.create_hearing(create_hearing_payload(ctx["disqualification"]["id"]), ADJUDICATOR)
    validate_error(resp, ApiErrorId.ERR_ADH_NOT_REFERRED.value)


def test_schedule_hearing_succeeds_after_referral(api):
    """PRD 3.5: "An `Adjudicator` schedules a **Hearing** for an `ADH_REFERRED`
    disqualification by supplying `disqualification_id` and a `scheduled_date`; the hearing
    enters `SCHEDULED`."

    Design: Difficulty/cross_entity_state_dependency/schedule_hearing_requires_adh_referred
    """
    ctx = create_substantiated_case(api)
    add_adh_referred_disqualification(api, ctx)
    resp = api.create_hearing(create_hearing_payload(ctx["disqualification"]["id"]), ADJUDICATOR)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SCHEDULED", f"expected SCHEDULED, got {data['status']}"


# --------------------------------------------------------------------------- #
# Corner: penalty, terminal lockdown, segregation, already-disqualified
# --------------------------------------------------------------------------- #
def test_first_offense_penalty_months(api):
    """PRD 3.5: "a count of 0 yields `penalty_months` of 12 with `is_permanent` false; a
    count of 1 yields `penalty_months` of 24 with `is_permanent` false; a count of 2 or
    more yields a permanent (third-strike) ban, with `penalty_months` null and
    `is_permanent` true."

    Design: Corner/calculations/disqualification_penalty_first_offense
    """
    ctx = setup_imposed_disqualification(api)
    disq = validate_success(api.get_disqualification(ctx["disqualification"]["id"], ADJUDICATOR))
    assert_disqualification(disq)
    assert disq["penalty_months"] == 12, f"expected 12, got {disq['penalty_months']}"
    assert disq["is_permanent"] is False, f"expected is_permanent False, got {disq['is_permanent']}"


def test_decide_after_decided_returns_already_terminal(api):
    """PRD 2.9: "whether the transition was attempted from a terminal state
    (`ERR_ALREADY_TERMINAL`, HTTP 409)."
    PRD 3.5: "An `outcome` of `IPV` advances the hearing to `DECIDED_IPV`, sets `outcome`
    to `IPV`, and imposes the linked disqualification."

    Design: Corner/state_machines/decide_after_decided_returns_already_terminal
    """
    ctx = setup_imposed_disqualification(api)  # hearing already DECIDED_IPV
    resp = api.decide_hearing(ctx["hearing"]["id"], decide_hearing_payload("NO_IPV"), ADJUDICATOR)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL.value)


def test_segregation_of_duties_blocks_investigator_deciding(api):
    """PRD 3.5: "Before any branch runs, the segregation-of-duties rule is enforced: the
    acting `Adjudicator`'s `X-User-ID` must differ from the `assigned_investigator_id` of
    the case underlying the hearing, and a match is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/validations/segregation_of_duties_investigator_decides
    """
    ctx = setup_held_hearing(api)  # case assigned to inv-1
    # Acting adjudicator uses the same X-User-ID as the assigned investigator.
    resp = api.decide_hearing(
        ctx["hearing"]["id"], decide_hearing_payload("IPV"), make_adjudicator_headers("inv-1")
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_propose_for_already_disqualified_subject_rejected(api):
    """PRD 3.5: "A proposal is refused with `ERR_SUBJECT_ALREADY_DISQUALIFIED` (HTTP 409)
    if the subject already carries an active imposed disqualification — that is, if the
    subject's `disqualification_status` is `DISQUALIFIED` or `PERMANENTLY_DISQUALIFIED`."

    Design: Corner/validations/subject_already_disqualified_on_propose
    """
    ctx = setup_imposed_disqualification(api)  # subject now DISQUALIFIED
    resp = api.create_disqualification(
        create_disqualification_payload(ctx["case"]["id"]), INVESTIGATOR
    )
    validate_error(resp, ApiErrorId.ERR_SUBJECT_ALREADY_DISQUALIFIED.value)
