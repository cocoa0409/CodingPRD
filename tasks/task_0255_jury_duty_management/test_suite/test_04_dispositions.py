"""Deferral, excusal, and exemption: the QUALIFIED_PENDING branch fork, the
deferral cascade and limit, role-split decision authority, and terminal lockdown.

Translates difficulty-design instances `non_linear_state_machine /
summons_branch_qualify_defer_excuse_exempt`, `priority_pair_validation_conflict /
role_mismatch_beats_invalid_state_on_decide`, and `compensating_invariant /
defer_conserves_open_summons_obligation` (queue A), plus corner-design instances
from §1.9 section `state_machines` (queue B).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    disposition_payload, decide_payload,
    TEST_USERS, make_juror_headers,
    create_term, add_juror, admin_qualify, open_term, draw,
    submit_qualifying_questionnaire, request_disposition, decide,
    get_summons, setup_qualified_pending, setup_pending_defer, setup_pending_excuse,
)

_ADMIN = TEST_USERS["jury_administrator_headers"]
_CLERK = TEST_USERS["court_clerk_headers"]


# ─── Difficulty: summons branch fork (DEFER re-issues) ─────────────────

def test_granted_defer_moves_summons_to_deferred(api):
    """PRD §3.5: "When a `DEFER` is granted, the original summons moves from
    `QUALIFIED_PENDING` to the terminal `DEFERRED` state with its
    `deferred_to_term_id` set to the requested term."

    Design: Difficulty/non_linear_state_machine/summons_branch_qualify_defer_excuse_exempt
    """
    s = setup_pending_defer()
    decide(s["disposition"]["id"], "GRANTED", _ADMIN)
    summons = get_summons(s["summons"]["id"])
    assert summons["status"] == "DEFERRED", f"expected DEFERRED, got {summons['status']}"
    assert summons["deferred_to_term_id"] == s["next_term"]["id"], (
        "deferred_to_term_id must be set to the requested term"
    )


def test_granted_defer_reissues_new_summoned_summons(api):
    """PRD §3.5: "a new summons in `SUMMONED` status is created on the requested
    term for the same juror, with a `badge_number` minted on that target term and a
    `deferral_count` equal to the original summons's `deferral_count` plus one."

    Design: Difficulty/non_linear_state_machine/summons_branch_qualify_defer_excuse_exempt
    """
    s = setup_pending_defer()
    decide(s["disposition"]["id"], "GRANTED", _ADMIN)
    resp = api.list_juror_summonses(s["juror"]["id"], _ADMIN, params={"status": "SUMMONED"})
    new_summonses = validate_success(resp)
    assert len(new_summonses) == 1, f"exactly one new SUMMONED summons expected, got {len(new_summonses)}"
    new = new_summonses[0]
    assert new["service_term_id"] == s["next_term"]["id"], "new summons must live on the requested term"
    assert new["deferral_count"] == 1, f"new deferral_count must be 1, got {new['deferral_count']}"


# ─── Difficulty: role-mismatch (auth) pre-empts invalid-state ──────────

def test_wrong_office_deciding_decided_disposition_is_role_mismatch(api):
    """PRD §3.5: "A `DEFER` may be decided only by a `JuryAdministrator` ... A
    decision made by the wrong office for the kind is rejected with
    `ERR_DISPOSITION_ROLE_MISMATCH` (HTTP 403)."
    PRD §4: "Authentication and authorization are evaluated first on every request,
    followed by existence checks, state checks, business and temporal rules,
    optimistic-concurrency checks, and finally request-body validation, in the
    priority order described throughout §2 and §3."

    Design: Difficulty/priority_pair_validation_conflict/role_mismatch_beats_invalid_state_on_decide
    """
    s = setup_pending_defer()
    # Already GRANTED by the administrator → no longer PENDING (would be invalid-state).
    decide(s["disposition"]["id"], "GRANTED", _ADMIN)
    # A CourtClerk is the wrong office for a DEFER; auth is evaluated before state.
    resp = api.decide_disposition(s["disposition"]["id"], decide_payload("DENIED"), _CLERK)
    validate_error(resp, ApiErrorId.ERR_DISPOSITION_ROLE_MISMATCH.value)


def test_courtclerk_deciding_pending_defer_is_role_mismatch(api):
    """PRD §3.5: "A `DEFER` may be decided only by a `JuryAdministrator`; an
    `EXCUSE` or `EXEMPT` may be decided only by a `CourtClerk`. A decision made by
    the wrong office for the kind is rejected with `ERR_DISPOSITION_ROLE_MISMATCH`
    (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/role_mismatch_beats_invalid_state_on_decide
    """
    s = setup_pending_defer()
    # Disposition still PENDING; only the wrong-office auth condition is violated.
    resp = api.decide_disposition(s["disposition"]["id"], decide_payload("GRANTED"), _CLERK)
    validate_error(resp, ApiErrorId.ERR_DISPOSITION_ROLE_MISMATCH.value)
    assert get_summons(s["summons"]["id"])["status"] == "QUALIFIED_PENDING"


# ─── Difficulty: defer conserves the juror's active-summons obligation ─

def test_defer_closes_original_obligation(api):
    """PRD §3.5: "When a `DEFER` is granted, the original summons moves from
    `QUALIFIED_PENDING` to the terminal `DEFERRED` state."

    Design: Difficulty/compensating_invariant/defer_conserves_open_summons_obligation
    """
    s = setup_pending_defer(report_date="2026-07-01T00:00:00Z",
                            next_report_date="2026-11-01T00:00:00Z")
    decide(s["disposition"]["id"], "GRANTED", _ADMIN)
    assert get_summons(s["summons"]["id"])["status"] == "DEFERRED", (
        "original summons must leave the active set as DEFERRED"
    )


def test_defer_reissues_exactly_one_active_summons(api):
    """PRD §3.5: "the system cascades a fresh summons into being: a new summons in
    `SUMMONED` status is created on the requested term for the same juror ... with a
    `deferral_count` equal to the original summons's `deferral_count` plus one."

    Design: Difficulty/compensating_invariant/defer_conserves_open_summons_obligation
    """
    s = setup_pending_defer(report_date="2026-07-01T00:00:00Z",
                            next_report_date="2026-11-01T00:00:00Z")
    decide(s["disposition"]["id"], "GRANTED", _ADMIN)
    all_summonses = validate_success(api.list_juror_summonses(s["juror"]["id"], _ADMIN))
    active = [x for x in all_summonses if x["status"] in (
        "SUMMONED", "QUALIFIED_PENDING", "REPORTING", "SERVING"
    )]
    assert len(active) == 1, f"exactly one active obligation must remain, got {len(active)}"
    assert active[0]["status"] == "SUMMONED"
    assert active[0]["deferral_count"] == 1, "the reissued summons carries deferral_count 1"


# ─── Corner: EXCUSE / EXEMPT grant branches ────────────────────────────

def test_granted_excuse_moves_to_terminal_excused(api):
    """PRD §3.5: "A granted `EXCUSE` moves the summons from `QUALIFIED_PENDING` to
    the terminal `EXCUSED` state, and a granted `EXEMPT` moves it to the terminal
    `EXEMPT` state; both end panel eligibility."
    PRD §3.5: "On any decision the deciding actor's role is stamped into
    `decided_by_role`."

    Design: Corner/state_machines/excuse_branch_grants_terminal_excused
    """
    s = setup_pending_excuse(kind="EXCUSE", reason_code="MEDICAL")
    disp = decide(s["disposition"]["id"], "GRANTED", _CLERK)
    assert disp["decision"] == "GRANTED"
    assert disp["decided_by_role"] == "CourtClerk", (
        f"decided_by_role must stamp the deciding office, got {disp['decided_by_role']}"
    )
    assert get_summons(s["summons"]["id"])["status"] == "EXCUSED"


def test_granted_exempt_moves_to_terminal_exempt(api):
    """PRD §3.5: "A granted `EXCUSE` moves the summons from `QUALIFIED_PENDING` to
    the terminal `EXCUSED` state, and a granted `EXEMPT` moves it to the terminal
    `EXEMPT` state; both end panel eligibility."

    Design: Corner/state_machines/exempt_branch_grants_terminal_exempt
    """
    s = setup_pending_excuse(kind="EXEMPT", reason_code="AGE")
    decide(s["disposition"]["id"], "GRANTED", _CLERK)
    assert get_summons(s["summons"]["id"])["status"] == "EXEMPT"


# ─── Corner: deferral limit (third attempt blocked) ────────────────────

def test_third_deferral_grant_blocked(api):
    """PRD §3.5: "A summons may be deferred at most twice — concretely, a `DEFER`
    may be granted only while the summons's `deferral_count` is below 2; granting a
    third would exceed the limit and is rejected with `ERR_DEFERRAL_LIMIT`
    (HTTP 409)."

    Design: Corner/state_machines/deferral_third_attempt_blocked
    """
    # Build a lineage deferred twice, landing on a third term as deferral_count 2.
    t1 = create_term(name="D-T1", report_date="2026-07-01T00:00:00Z")
    t2 = create_term(name="D-T2", report_date="2026-08-01T00:00:00Z")
    t3 = create_term(name="D-T3", report_date="2026-09-01T00:00:00Z")
    t4 = create_term(name="D-T4", report_date="2026-10-01T00:00:00Z")

    juror = add_juror(t1["id"], full_name="Yul J")
    admin_qualify(juror["id"])
    open_v = open_term(t1["id"])["version"]
    s1 = draw(t1["id"], open_v, count=1)[0]
    submit_qualifying_questionnaire(s1["id"], juror["id"])
    d1 = request_disposition(s1["id"], juror["id"], "DEFER", "HARDSHIP", requested_term_id=t2["id"])
    decide(d1["id"], "GRANTED", _ADMIN)

    # Re-issued summons on t2 (deferral_count 1).
    s2_list = validate_success(api.list_juror_summonses(juror["id"], _ADMIN, params={"status": "SUMMONED"}))
    s2 = next(x for x in s2_list if x["service_term_id"] == t2["id"])
    submit_qualifying_questionnaire(s2["id"], juror["id"])
    d2 = request_disposition(s2["id"], juror["id"], "DEFER", "HARDSHIP", requested_term_id=t3["id"])
    decide(d2["id"], "GRANTED", _ADMIN)

    # Re-issued summons on t3 (deferral_count 2): a third grant must fail.
    s3_list = validate_success(api.list_juror_summonses(juror["id"], _ADMIN, params={"status": "SUMMONED"}))
    s3 = next(x for x in s3_list if x["service_term_id"] == t3["id"])
    assert s3["deferral_count"] == 2, f"third summons must carry deferral_count 2, got {s3['deferral_count']}"
    submit_qualifying_questionnaire(s3["id"], juror["id"])
    d3 = request_disposition(s3["id"], juror["id"], "DEFER", "HARDSHIP", requested_term_id=t4["id"])

    resp = api.decide_disposition(d3["id"], decide_payload("GRANTED"), _ADMIN)
    validate_error(resp, ApiErrorId.ERR_DEFERRAL_LIMIT.value)
    assert get_summons(s3["id"])["status"] == "QUALIFIED_PENDING"


# ─── Corner: terminal-state lockdown on release ────────────────────────

def test_release_excused_summons_invalid_state(api):
    """PRD §3.9: "A release requested from any other state is an invalid-state
    condition."

    Design: Corner/state_machines/release_terminal_summons_invalid_state
    """
    s = setup_pending_excuse(kind="EXCUSE", reason_code="CAREGIVER")
    decide(s["disposition"]["id"], "GRANTED", _CLERK)  # summons -> EXCUSED (terminal)
    resp = api.release_summons(s["summons"]["id"], _CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert get_summons(s["summons"]["id"])["status"] == "EXCUSED"


# ─── Corner: invalid enum on disposition kind ──────────────────────────

def test_invalid_disposition_kind_rejected(api):
    """PRD §3.9: "Every request body is finally checked for required fields, valid
    enum membership, and in-range numeric values; a missing field, a bad enum, or
    an out-of-range value is rejected with `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/invalid_enum_disposition_kind_rejected
    """
    s = setup_qualified_pending(term_overrides={"name": "C7"})
    resp = api.create_disposition(
        s["summons"]["id"],
        disposition_payload("POSTPONE", "OTHER"),
        make_juror_headers(s["juror"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
