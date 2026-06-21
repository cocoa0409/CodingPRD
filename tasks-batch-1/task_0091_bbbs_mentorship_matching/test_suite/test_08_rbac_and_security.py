"""Role-based access control, authentication, segregation-of-duties, and the
state-beats-safety validation-priority pair.

Queue-B rbac corners plus the queue-A priority_pair (state vs safety).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    factories as f,
    fixtures as fx,
)
from test_helpers.test_users import (
    make_supervisor_headers,
    make_headers,
)

COORD = fx.COORD
SCREENER = fx.SCREENER
SPECIALIST = fx.SPECIALIST


def test_match_specialist_cannot_adjudicate_check(api):
    """PRD §4 endpoint table: `POST /background-checks/{id}/adjudicate` is
    authorized for `BackgroundScreener` only.
    PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation under the matrix in §4, the
    request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/matchspecialist_cannot_adjudicate_check
    """
    fx.set_clock(fx.REF_CLOCK)
    vol = fx.create_volunteer(set_clock_first=False, full_name="V Rb")
    validate_success(api.submit_screening(vol["id"], SCREENER), 200)
    crim, _dmv, _car = fx.screen_check_ids(vol["id"])
    resp = api.adjudicate_check(crim, f.adjudicate_payload("CLEAR", 0), SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_background_screener_cannot_propose_match(api):
    """PRD §4 endpoint table: `POST /children/{id}/propose-match` is authorized
    for `MatchSpecialist` only.
    PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation under the matrix in §4, the
    request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/backgroundscreener_cannot_propose_match
    """
    fx.set_clock(fx.REF_CLOCK)
    fx.create_eligible_volunteer(set_clock_first=False, full_name="V Rb2")
    guardian = fx.create_guardian(consent_on_file=True, full_name="G Rb2")
    child = fx.create_child(guardian["id"], first_name="Rb")
    resp = api.propose_match(
        child["id"], {"expected_child_version": child["version"]}, SCREENER
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_unrecognized_role_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or the role is not one the system
    recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    fx.set_clock(fx.REF_CLOCK)
    vol = fx.create_volunteer(set_clock_first=False, full_name="V Ua")
    anon = make_headers("anon-1", "Anonymous")
    resp = api.get_volunteer(vol["id"], anon)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_segregation_of_duties_same_user_finalize_denied(api):
    """PRD §3.7: "the finalizing supervisor must not be the same operator who
    confirmed the match: if the `X-User-ID` finalizing the exit equals the
    `X-User-ID` recorded as the confirming match specialist, the request is
    rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/segregation_of_duties_finalize_denied
    """
    # Confirm the match acting as MatchSpecialist with operator identity "dual-1".
    ctx = fx.setup_active_match(
        clock=fx.REF_CLOCK,
        volunteer_overrides={"full_name": "V Sd"},
        guardian_overrides={"full_name": "G Sd"},
        child_overrides={"first_name": "Sd"},
        confirm_specialist_id="dual-1",
    )
    et = fx.open_exit(ctx["match"]["id"], exit_type="EARLY_TERMINATION",
                      reason_code="SAFETY_CONCERN", specialist_headers=ctx["specialist_headers"])
    # The SAME operator "dual-1" attempts to finalize as Supervisor.
    same_user_supervisor = make_supervisor_headers("dual-1")
    resp = api.finalize_exit(et["id"], same_user_supervisor)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)


def test_adjudicate_state_check_precedes_adverse_safety(api):
    """PRD §2.6: "(6) the state-machine precondition that the target resource is
    in a state from which the requested transition is defined, yielding
    `ERR_INVALID_STATE`; and only then (7 and beyond) the domain-specific
    business rules described throughout §3, each with its own error."

    Design: Difficulty/priority_pair_validation_conflict/adjudicate_state_beats_adverse_safety
    """
    fx.set_clock(fx.REF_CLOCK)
    vol = fx.create_volunteer(set_clock_first=False, full_name="V PV1",
                             interest_tags=["STEM"])
    validate_success(api.submit_screening(vol["id"], SCREENER), 200)
    crim, _dmv, _car = fx.screen_check_ids(vol["id"])
    # First CLEAR succeeds.
    validate_success(api.adjudicate_check(crim, f.adjudicate_payload("CLEAR", 0), SCREENER), 200)
    # Second adjudicate on the now-CLEARED check, also carrying an over-tolerance
    # adverse_findings: the state check (priority 6) pre-empts the safety check
    # (priority 7+), so ERR_INVALID_STATE is returned.
    resp = api.adjudicate_check(crim, f.adjudicate_payload("CLEAR", 3), SCREENER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_adjudicate_state_check_fires_even_without_safety_violation(api):
    """PRD §2.6: "(6) the state-machine precondition that the target resource is
    in a state from which the requested transition is defined, yielding
    `ERR_INVALID_STATE`; and only then (7 and beyond) the domain-specific business
    rules".

    Design: Difficulty/priority_pair_validation_conflict/adjudicate_state_beats_adverse_safety
    """
    fx.set_clock(fx.REF_CLOCK)
    vol = fx.create_volunteer(set_clock_first=False, full_name="V PV2",
                             interest_tags=["STEM"])
    validate_success(api.submit_screening(vol["id"], SCREENER), 200)
    crim, _dmv, _car = fx.screen_check_ids(vol["id"])
    validate_success(api.adjudicate_check(crim, f.adjudicate_payload("CLEAR", 0), SCREENER), 200)
    # Re-adjudicating the now-CLEARED (terminal-for-this-transition) check with an
    # in-tolerance finding still trips the state gate first → ERR_INVALID_STATE.
    resp = api.adjudicate_check(crim, f.adjudicate_payload("CLEAR", 0), SCREENER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
