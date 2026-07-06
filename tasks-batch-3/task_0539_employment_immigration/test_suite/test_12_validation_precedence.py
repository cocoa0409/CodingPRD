"""Validation precedence: temporal gate beats structural completeness, and state
legality beats cross-entity referential gates (PRD §2.9).

Queue A / Difficulty — rule `priority_pair_validation_conflict`.
"""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    setup_recruiting_perm_case, setup_submitted_h1b_petition, set_clock,
    make_employer_agent_headers,
)


def test_quiet_period_reports_too_short_over_incomplete(api):
    """PRD §2.9: "A concrete consequence of this ordering: when an employer tries
    to enter the quiet period too early **and** with an incomplete recruitment
    record, the too-short temporal failure (`ERR_RECRUITMENT_TOO_SHORT`, priority
    9) is reported before the incompleteness failure (`ERR_RECRUITMENT_INCOMPLETE`,
    priority 10)."

    Design: Difficulty/priority_pair_validation_conflict/quiet_period_temporal_beats_recruitment_constraint
    """
    employer, pwd, pc = setup_recruiting_perm_case()  # recruitment_start 2026-05-01, no steps
    hdr = make_employer_agent_headers(employer["id"])
    set_clock("2026-05-06T00:00:00Z")  # only 5 days elapsed AND no recruitment steps
    res = api.transition_perm_case(pc["id"], {"to_status": "QUIET_PERIOD"}, hdr)
    validate_error(res, ApiErrorId.ERR_RECRUITMENT_TOO_SHORT, expected_status=422)


def test_quiet_period_conflict_leaves_case_recruiting(api):
    """PRD §2.9: "the checks run in a fixed priority order, and the first failure
    determines the returned error."

    Design: Difficulty/priority_pair_validation_conflict/quiet_period_temporal_beats_recruitment_constraint
    """
    employer, pwd, pc = setup_recruiting_perm_case()
    hdr = make_employer_agent_headers(employer["id"])
    set_clock("2026-05-06T00:00:00Z")
    api.transition_perm_case(pc["id"], {"to_status": "QUIET_PERIOD"}, hdr)
    assert validate_success(api.get_perm_case(pc["id"], hdr), 200)["status"] == "RECRUITING"


def test_resubmit_after_cascade_deny_reports_invalid_state_over_referential(api):
    """PRD §2.9: "the requested transition is defined from the resource's current
    state; otherwise `ERR_INVALID_STATE` (409)."
    PRD §2.9: "This ordering matters: a later, more specific rejection must never
    mask an earlier, more general one."

    Design: Difficulty/priority_pair_validation_conflict/petition_submit_state_beats_referential
    """
    ctx = setup_submitted_h1b_petition()
    hdr = make_employer_agent_headers(ctx["employer"]["id"])
    # Withdrawing the certified LCA cascades the SUBMITTED petition to DENIED.
    validate_success(api.transition_lca(ctx["lca"]["id"], {"to_status": "WITHDRAWN"}, hdr), 200)
    res = api.transition_h1b_petition(ctx["petition"]["id"], {"to_status": "SUBMITTED"}, hdr)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_resubmit_after_cascade_deny_leaves_petition_denied(api):
    """PRD §3.4: "Withdrawal both subtracts the application's locked
    `required_wage_cents` back out of the employer's `total_wage_obligation_cents`
    and cascades to petitions: every `H1BPetition` whose `lca_id` points at this
    application and whose `status` is `DRAFT`, `SUBMITTED`, or `RFE_ISSUED` is
    transitioned to `DENIED`."

    Design: Difficulty/priority_pair_validation_conflict/petition_submit_state_beats_referential
    """
    ctx = setup_submitted_h1b_petition()
    hdr = make_employer_agent_headers(ctx["employer"]["id"])
    validate_success(api.transition_lca(ctx["lca"]["id"], {"to_status": "WITHDRAWN"}, hdr), 200)
    api.transition_h1b_petition(ctx["petition"]["id"], {"to_status": "SUBMITTED"}, hdr)
    assert validate_success(api.get_h1b_petition(ctx["petition"]["id"], hdr), 200)["status"] == "DENIED"
