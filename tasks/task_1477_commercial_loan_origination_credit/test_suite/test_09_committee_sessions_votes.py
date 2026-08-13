"""Committee voting: quorum/decline closure, the remand cycle, session windows,
duplicate votes, and the decision-open OCC checkpoint (PRD sections 2.6, 2.7, 3.5).
"""
from test_helpers import (
    ApiErrorId, api_client, approve_decision, cast_vote, clear_exceptions,
    create_session, deal_committee_review, deal_decision_open, get_application,
    make_committee_member_headers, open_decision, set_clock, setup_officers,
    submit_to_committee, validate_error, validate_paginated, validate_success,
)


def test_chair_remand_returns_application_to_exception_review():
    """PRD section 3.5: "a `REMANDED` decision returns it to `EXCEPTION_REVIEW` for
    the exception loop of section 3.3, after which re-submission may open a fresh
    decision" and "a chair's `REMAND` closes it `REMANDED` immediately, regardless
    of tally."

    Design: Difficulty/non_linear_state_machine/committee_remand_cycle_returns_to_exception_review
    """
    ctx = deal_decision_open()
    o = ctx["o"]
    remanded = cast_vote(o, ctx["decision"]["id"], "ch", "REMAND")
    assert remanded["status"] == "REMANDED", "chair REMAND closes the decision immediately"

    app = get_application(o, ctx["application"]["id"])
    assert app["status"] == "EXCEPTION_REVIEW", "the remand cycle re-enters exception review"


def test_remand_cycle_completes_with_fresh_decision():
    """PRD section 3.5: "a `REMANDED` decision returns it to `EXCEPTION_REVIEW` for
    the exception loop of section 3.3, after which re-submission may open a fresh
    decision" and "an `APPROVED` decision moves it `COMMITTEE_REVIEW` →
    `TERM_SHEET_NEGOTIATION`".

    Design: Difficulty/non_linear_state_machine/committee_remand_cycle_returns_to_exception_review
    """
    ctx = deal_decision_open()
    o = ctx["o"]
    v1 = get_application(o, ctx["application"]["id"])["version"]
    cast_vote(o, ctx["decision"]["id"], "ch", "REMAND")

    # Exception loop: zero OPEN exceptions on this clean deal, so clearing succeeds.
    cleared = clear_exceptions(o, ctx["application"]["id"])
    assert cleared["status"] == "APPRAISAL_REVIEW"

    resized = submit_to_committee(o, ctx["application"]["id"])
    assert resized["status"] == "COMMITTEE_REVIEW"
    assert resized["proposed_amount_cents"] == 200_000_000
    assert resized["version"] > v1, "version advanced at every hop"

    ctx["session"] = create_session(o, level="STANDARD", starts_at="2026-08-10T16:00:00Z",
                                    ends_at="2026-08-10T17:00:00Z")
    set_clock("2026-08-10T16:15:00Z")
    ctx["decision"] = open_decision(o, ctx["application"]["id"], ctx["session"]["id"])
    approve_decision(ctx, level="STANDARD")
    assert ctx["decision"]["status"] == "APPROVED"
    assert ctx["application"]["status"] == "TERM_SHEET_NEGOTIATION"

    # The remanded first decision stays terminal.
    rows, _ = validate_paginated(api_client.list_application_decisions(
        ctx["application"]["id"], o["ch"]["headers"]))
    by_id = {d["id"]: d for d in rows}
    assert len(rows) == 2
    first_id = [d for d in rows if d["id"] != ctx["decision"]["id"]][0]["id"]
    assert by_id[first_id]["status"] == "REMANDED"


def _session_window_deal():
    """Application at COMMITTEE_REVIEW with session in window and OPEN decision."""
    return deal_decision_open()


def test_vote_after_session_adjourned_rejected():
    """PRD section 2.6: "Any committee session whose `ends_at` is at or before the
    current clock instant transitions from `SCHEDULED` to `ADJOURNED`, after which
    its open decisions can no longer receive votes."
    PRD section 3.5: "the logical clock must lie within the session's window — on or
    after `starts_at` and strictly before `ends_at` — while the session is still
    `SCHEDULED` (`ERR_COMMITTEE_SESSION_NOT_OPEN`)."

    Design: Difficulty/cross_entity_state_dependency/vote_blocked_by_session_window_state
    """
    ctx = _session_window_deal()
    o = ctx["o"]
    set_clock("2026-08-10T15:30:00Z")  # session ends_at 15:30 (STANDARD window 14:00-15:30)

    sess = validate_success(api_client.get_committee_session(ctx["session"]["id"], o["ch"]["headers"]), 200)
    assert sess["status"] == "ADJOURNED"

    resp = api_client.cast_vote(ctx["decision"]["id"], {"vote": "APPROVE"}, o["m1"]["headers"])
    validate_error(resp, ApiErrorId.ERR_COMMITTEE_SESSION_NOT_OPEN)


def test_rejected_vote_leaves_decision_untouched():
    """PRD section 3.5: "the logical clock must lie within the session's window — on
    or after `starts_at` and strictly before `ends_at` — while the session is still
    `SCHEDULED` (`ERR_COMMITTEE_SESSION_NOT_OPEN`)" — a rejected ballot records
    nothing.

    Design: Difficulty/cross_entity_state_dependency/vote_blocked_by_session_window_state
    """
    ctx = _session_window_deal()
    o = ctx["o"]
    set_clock("2026-08-10T15:30:00Z")
    validate_error(api_client.cast_vote(ctx["decision"]["id"], {"vote": "APPROVE"}, o["m1"]["headers"]),
                   ApiErrorId.ERR_COMMITTEE_SESSION_NOT_OPEN)

    rows, _ = validate_paginated(api_client.list_application_decisions(
        ctx["application"]["id"], o["ch"]["headers"]))
    dec = rows[0]
    assert dec["status"] == "OPEN"
    assert dec["votes_for"] == 0, "the rejected vote recorded nothing"

    app = get_application(o, ctx["application"]["id"])
    assert app["status"] == "COMMITTEE_REVIEW", "no transition fired"


def test_duplicate_vote_rejected():
    """PRD section 3.5: "the officer must not already have a ballot recorded on this
    decision (`ERR_DUPLICATE_VOTE`)".

    Design: Corner/validations/duplicate_vote_rejected
    """
    ctx = _session_window_deal()
    o = ctx["o"]
    first = cast_vote(o, ctx["decision"]["id"], "m1", "APPROVE")
    assert first["votes_for"] == 1

    dup = api_client.cast_vote(ctx["decision"]["id"], {"vote": "APPROVE"}, o["m1"]["headers"])
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_VOTE)

    rows, _ = validate_paginated(api_client.list_application_decisions(
        ctx["application"]["id"], o["ch"]["headers"]))
    assert rows[0]["votes_for"] == 1
    assert rows[0]["status"] == "OPEN", "STANDARD quorum 2 not reached"


def test_vote_before_session_window_rejected():
    """PRD section 3.5: "the logical clock must lie within the session's window — on
    or after `starts_at` and strictly before `ends_at` — while the session is still
    `SCHEDULED` (`ERR_COMMITTEE_SESSION_NOT_OPEN`)." PRD section 2.6: "At server
    startup the logical clock is set to exactly `2026-08-01T00:00:00Z`".

    Design: Corner/validations/vote_before_session_window_rejected
    """
    # Decision opened with the clock at its 2026-08-01 default (before the window).
    ctx = deal_decision_open(set_the_clock=False)
    o = ctx["o"]
    assert ctx["decision"]["status"] == "OPEN"

    resp = api_client.cast_vote(ctx["decision"]["id"], {"vote": "APPROVE"}, o["m1"]["headers"])
    validate_error(resp, ApiErrorId.ERR_COMMITTEE_SESSION_NOT_OPEN)

    sess = validate_success(api_client.get_committee_session(ctx["session"]["id"], o["ch"]["headers"]), 200)
    assert sess["status"] == "SCHEDULED", "early is not adjourned"
    rows, _ = validate_paginated(api_client.list_application_decisions(
        ctx["application"]["id"], o["ch"]["headers"]))
    assert rows[0]["votes_for"] == 0


def test_committee_session_adjourns_on_clock_sweep():
    """PRD section 2.6: "Any committee session whose `ends_at` is at or before the
    current clock instant transitions from `SCHEDULED` to `ADJOURNED`".

    Design: Corner/state_machines/committee_session_adjourns_on_clock_sweep
    """
    o = setup_officers(["ch"])
    sess = validate_success(api_client.create_committee_session(
        {"level": "STANDARD", "starts_at": "2026-08-10T14:00:00Z",
         "ends_at": "2026-08-10T15:00:00Z"}, o["ch"]["headers"]), 201)
    assert sess["status"] == "SCHEDULED"

    set_clock("2026-08-10T15:00:00Z")
    after = validate_success(api_client.get_committee_session(sess["id"], o["ch"]["headers"]), 200)
    assert after["status"] == "ADJOURNED", "the half-open window excludes its own endpoint"


def test_remand_vote_denied_for_committee_member():
    """PRD section 2.1: "only a `CommitteeChair` may cast a REMAND vote".
    PRD section 3.5: "a `REMAND` may be cast only by the `CommitteeChair`
    (`ERR_ONLY_CHAIR_MAY_REMAND`, HTTP 403)."

    Design: Corner/rbac/remand_vote_denied_for_committee_member
    """
    ctx = _session_window_deal()
    o = ctx["o"]
    resp = api_client.cast_vote(ctx["decision"]["id"], {"vote": "REMAND"}, o["m1"]["headers"])
    validate_error(resp, ApiErrorId.ERR_ONLY_CHAIR_MAY_REMAND)

    rows, _ = validate_paginated(api_client.list_application_decisions(
        ctx["application"]["id"], o["ch"]["headers"]))
    assert rows[0]["status"] == "OPEN"
    assert rows[0]["votes_for"] == 0


def test_vote_denied_for_credit_analyst():
    """PRD section 2.1: "An authenticated caller who attempts an operation their role
    is not permitted to perform is rejected with `ERR_INSUFFICIENT_PERMISSIONS`".
    PRD section 4: the votes endpoint is restricted to "CommitteeMember,
    CommitteeChair".

    Design: Corner/rbac/vote_denied_for_credit_analyst
    """
    ctx = _session_window_deal()
    o = ctx["o"]
    resp = api_client.cast_vote(ctx["decision"]["id"], {"vote": "APPROVE"}, o["an"]["headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    rows, _ = validate_paginated(api_client.list_application_decisions(
        ctx["application"]["id"], o["ch"]["headers"]))
    assert rows[0]["status"] == "OPEN"
    assert rows[0]["votes_for"] == 0


def test_sod_committee_recusal_rejected():
    """PRD section 2.9: "An officer may not vote on a committee decision for an
    application whose `originating_officer_id` is their own `id`; a violation is
    rejected with `ERR_SOD_COMMITTEE_RECUSAL`."

    Design: Corner/rbac/sod_committee_recusal_rejected
    """
    ctx = _session_window_deal()
    o = ctx["o"]
    # The originator (rm) votes wearing a CommitteeMember hat.
    resp = api_client.cast_vote(ctx["decision"]["id"], {"vote": "APPROVE"},
                                make_committee_member_headers(o["rm"]["id"]))
    validate_error(resp, ApiErrorId.ERR_SOD_COMMITTEE_RECUSAL)

    rows, _ = validate_paginated(api_client.list_application_decisions(
        ctx["application"]["id"], o["ch"]["headers"]))
    assert rows[0]["votes_for"] == 0
    assert rows[0]["status"] == "OPEN"


def test_decision_create_denied_for_committee_member():
    """PRD section 4: opening a committee decision is restricted to `CommitteeChair`.
    PRD section 2.8: "The caller's role is permitted for this operation, including
    the operation-level restrictions that only a `CreditPolicyOfficer` may drive a
    checklist item to `WAIVED` and only a `CommitteeChair` may cast a REMAND vote;
    otherwise `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/decision_create_denied_for_committee_member
    """
    ctx = deal_committee_review(officer_keys=("rm", "an", "po", "apm", "ch", "m1"))
    o = ctx["o"]
    sess = create_session(o, level="STANDARD")
    resp = api_client.create_committee_decision(
        {"loan_application_id": ctx["application"]["id"], "committee_session_id": sess["id"],
         "expected_loan_application_version": ctx["application"]["version"]}, o["m1"]["headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    rows, meta = validate_paginated(api_client.list_application_decisions(
        ctx["application"]["id"], o["ch"]["headers"]))
    assert rows == [] and meta["total_count"] == 0


def test_session_create_denied_for_committee_member():
    """PRD section 4: scheduling a committee session is restricted to
    `CommitteeChair`. PRD section 2.1: "An authenticated caller who attempts an
    operation their role is not permitted to perform is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/session_create_denied_for_committee_member
    """
    o = setup_officers(["m1"])
    resp = api_client.create_committee_session(
        {"level": "STANDARD", "starts_at": "2026-08-10T14:00:00Z",
         "ends_at": "2026-08-10T15:00:00Z"}, o["m1"]["headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_occ_committee_decision_stale_version_rejected():
    """PRD section 2.7: "Opening a committee decision ... must carry the field
    `expected_loan_application_version` ... If the supplied value does not equal the
    application's current `version`, the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412)." PRD section 2.8: optimistic concurrency "runs after schema
    validation but before every remaining state and business check."

    Design: Corner/cross_cutting_complexity_layers/occ_committee_decision_stale_version_rejected
    """
    ctx = deal_decision_open()
    o = ctx["o"]
    # D1's creation bumped the application version by one; the pre-open version is stale.
    pre_open_version = ctx["application"]["version"]
    current = get_application(o, ctx["application"]["id"])
    assert current["version"] > pre_open_version

    resp = api_client.create_committee_decision(
        {"loan_application_id": ctx["application"]["id"],
         "committee_session_id": ctx["session"]["id"],
         "expected_loan_application_version": pre_open_version}, o["ch"]["headers"])
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    rows, meta = validate_paginated(api_client.list_application_decisions(
        ctx["application"]["id"], o["ch"]["headers"]))
    assert len(rows) == 1
    assert rows[0]["id"] == ctx["decision"]["id"]
    assert rows[0]["status"] == "OPEN"
