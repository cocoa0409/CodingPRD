"""Committee lifecycle transitions and the committee-must-be-ACTIVE gate on creates."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_contribution_payload,
    TEST_USERS, make_treasurer_headers,
    set_clock, register_committee, create_active_committee, add_contribution,
)

REGULATOR = TEST_USERS["regulator_headers"]


def test_approve_already_active_committee_rejected(api):
    """PRD §3.1: "Agency approval advances a committee from PENDING to ACTIVE; this is
    permitted only while the committee is PENDING, and an attempt against any other state
    is rejected with ERR_COMMITTEE_NOT_PENDING."

    Design: Corner/state_machines/committee_approve_when_active_rejected
    """
    committee = create_active_committee(api, name="Sig", committee_type="PAC")
    validate_error(api.approve_committee(committee["id"], REGULATOR), ApiErrorId.ERR_COMMITTEE_NOT_PENDING.value)


def test_suspend_terminated_committee_rejected(api):
    """PRD §3.1: "An agency operator may suspend an active committee, moving it from ACTIVE
    to SUSPENDED; this requires the committee to be ACTIVE and is otherwise rejected with
    ERR_COMMITTEE_NOT_ACTIVE."

    Design: Corner/state_machines/committee_terminated_terminal_lockdown
    """
    committee = create_active_committee(api, name="Tau", committee_type="PAC")
    cid = committee["id"]
    validate_success(api.terminate_committee(cid, make_treasurer_headers(cid)))
    validate_error(api.suspend_committee(cid, REGULATOR), ApiErrorId.ERR_COMMITTEE_NOT_ACTIVE.value)


def test_contribution_to_pending_committee_rejected(api):
    """PRD §3.1: "Only an ACTIVE committee may accept new contributions, expenditures, or
    reports; when the committee is in any other state those creates are refused with
    ERR_COMMITTEE_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/contribution_requires_committee_active
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    committee = register_committee(api, name="Lam")  # left PENDING (not approved)
    resp = api.create_contribution(
        committee["id"],
        create_contribution_payload(contributor_type="INDIVIDUAL", amount_cents=5000),
        make_treasurer_headers(committee["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COMMITTEE_NOT_ACTIVE.value)


def test_contribution_to_suspended_committee_rejected(api):
    """PRD §3.1: "Only an ACTIVE committee may accept new contributions, expenditures, or
    reports; when the committee is in any other state those creates are refused with
    ERR_COMMITTEE_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/contribution_requires_committee_active
    """
    committee = create_active_committee(api, name="LamSusp")
    validate_success(api.suspend_committee(committee["id"], REGULATOR))
    resp = api.create_contribution(
        committee["id"],
        create_contribution_payload(contributor_type="INDIVIDUAL", amount_cents=5000),
        make_treasurer_headers(committee["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COMMITTEE_NOT_ACTIVE.value)


def test_inactive_committee_gate_precedes_limit_check_error_id(api):
    """PRD §2.7: "Cross-entity state — related entities are in the required state ... the
    committee is ACTIVE for a contribution/expenditure/report create ... otherwise a 409
    such as ERR_COMMITTEE_NOT_ACTIVE" (step 9), evaluated before "Contribution limit ...
    otherwise ERR_CONTRIBUTION_LIMIT_EXCEEDED" (step 14).

    Design: Difficulty/priority_pair_validation_conflict/committee_inactive_beats_limit
    """
    committee = create_active_committee(api, name="Iota", committee_type="CANDIDATE")
    cid = committee["id"]
    # contributor r1 already at the exact INDIVIDUAL->CANDIDATE limit (330000)
    add_contribution(api, cid, contributor_ref="r1", contributor_type="INDIVIDUAL", amount_cents=330000)
    validate_success(api.suspend_committee(cid, REGULATOR))
    resp = api.create_contribution(
        cid,
        create_contribution_payload(contributor_ref="r1", contributor_type="INDIVIDUAL", amount_cents=1),
        make_treasurer_headers(cid),
    )
    validate_error(resp, ApiErrorId.ERR_COMMITTEE_NOT_ACTIVE.value)


def test_inactive_committee_gate_not_reported_as_limit_error(api):
    """PRD §2.7: the cross-entity committee-ACTIVE check (step 9) is evaluated before the
    contribution-limit check (step 14), "so that the earliest failing check determines the
    returned error."

    Design: Difficulty/priority_pair_validation_conflict/committee_inactive_beats_limit
    """
    committee = create_active_committee(api, name="Iota2", committee_type="CANDIDATE")
    cid = committee["id"]
    add_contribution(api, cid, contributor_ref="r1", contributor_type="INDIVIDUAL", amount_cents=330000)
    validate_success(api.suspend_committee(cid, REGULATOR))
    resp = api.create_contribution(
        cid,
        create_contribution_payload(contributor_ref="r1", contributor_type="INDIVIDUAL", amount_cents=1),
        make_treasurer_headers(cid),
    )
    err = validate_error(resp, ApiErrorId.ERR_COMMITTEE_NOT_ACTIVE.value)
    assert err["error_id"] != ApiErrorId.ERR_CONTRIBUTION_LIMIT_EXCEEDED.value, (
        "state gate (step 9) must pre-empt the limit check (step 14) even though the aggregate would exceed"
    )
