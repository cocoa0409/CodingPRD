"""Reporting scores and confirming: ties, competitor gate, state, SoD, OCC.

Queue B: report_tie_score_rejected, report_by_non_competitor_forbidden,
confirm_from_pending_invalid_state, sod_self_confirm_rejected,
occ_confirm_stale_match_version.
"""
from test_helpers import (
    validate_error, ApiErrorId,
    report_match_payload, confirm_match_payload, schedule_match_payload,
    TEST_USERS, make_referee_headers, make_player_headers,
)
from test_helpers import fixtures as F

DIRECTOR = TEST_USERS["director_headers"]
REFEREE = TEST_USERS["referee_headers"]


def test_report_tie_score_rejected(api):
    """PRD §3.5: "The scores must differ — ties are not permitted in bracket play,
    so equal scores are rejected with ERR_TIE_NOT_ALLOWED (HTTP 422)".

    Design: Corner/validations/report_tie_score_rejected
    """
    ctx = F.build_two_player_single_elim()
    F.schedule(ctx["m_id"], ctx["st_id"], window="a")
    resp = api.report_match(ctx["m_id"], report_match_payload(1, 1),
                            make_player_headers(ctx["p1"]))
    validate_error(resp, ApiErrorId.ERR_TIE_NOT_ALLOWED.value, 422)
    assert F.get_match(ctx["m_id"])["status"] == "SCHEDULED"


def test_report_by_non_competitor_forbidden(api):
    """PRD §3.5: "the reporter must be either a competitor of the match or a
    Referee, otherwise the report is rejected with ERR_NOT_A_COMPETITOR (HTTP 403)".

    Design: Corner/errors/report_by_non_competitor_forbidden
    """
    ctx = F.build_two_player_single_elim()
    F.schedule(ctx["m_id"], ctx["st_id"], window="a")
    outsider = F.create_player(rating=1100, display_name="P3")
    resp = api.report_match(ctx["m_id"], report_match_payload(2, 0),
                            make_player_headers(outsider["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_A_COMPETITOR.value, 403)
    assert F.get_match(ctx["m_id"])["status"] == "SCHEDULED"


def test_confirm_pending_match_invalid_state(api):
    """PRD §3.5: "a confirm: a Referee or Director moves the match REPORTED →
    CONFIRMED." PRD §2.11: the target's state precondition (ERR_INVALID_STATE)
    is checked before business rules such as the OCC/SoD checks.

    Design: Corner/state_machines/confirm_from_pending_invalid_state
    """
    ctx = F.build_two_player_single_elim()
    match = F.get_match(ctx["m_id"])  # still PENDING, never scheduled/reported
    resp = api.confirm_match(ctx["m_id"], confirm_match_payload(match["version"]),
                             make_referee_headers("ref-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert F.get_match(ctx["m_id"])["status"] == "PENDING"


def test_confirm_by_reporter_rejected_sod(api):
    """PRD §3.5: "the confirming X-User-ID must differ from reported_by_user_id,
    otherwise the confirm is rejected with ERR_SOD_SELF_CONFIRM (HTTP 409)".

    Design: Corner/rbac/sod_self_confirm_rejected
    """
    ctx = F.build_two_player_single_elim()
    F.schedule(ctx["m_id"], ctx["st_id"], window="a")
    reported = F.report_scores(ctx["m_id"], 2, 0, make_referee_headers("ref-7"))
    resp = api.confirm_match(ctx["m_id"], confirm_match_payload(reported["version"]),
                             make_referee_headers("ref-7"))
    validate_error(resp, ApiErrorId.ERR_SOD_SELF_CONFIRM.value, 409)
    assert F.get_match(ctx["m_id"])["status"] == "REPORTED"


def test_confirm_with_stale_match_version_rejected(api):
    """PRD §2.7: "Confirming a match requires expected_match_version ... If it does
    not equal the match's current version ... the confirm is rejected with
    ERR_STALE_MATCH_VERSION (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_confirm_stale_match_version
    """
    ctx = F.build_two_player_single_elim()
    scheduled = F.schedule(ctx["m_id"], ctx["st_id"], window="a")
    stale_version = scheduled["version"]
    # report bumps the match version, so the schedule-era version is now stale
    F.report_winner(ctx["m_id"], ctx["r1"], make_referee_headers("ref-rep"))
    resp = api.confirm_match(ctx["m_id"], confirm_match_payload(stale_version),
                             make_referee_headers("ref-conf"))
    validate_error(resp, ApiErrorId.ERR_STALE_MATCH_VERSION.value, 412)
    assert F.get_match(ctx["m_id"])["status"] == "REPORTED"
