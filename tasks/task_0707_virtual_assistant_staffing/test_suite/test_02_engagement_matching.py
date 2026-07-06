"""VA matching, auto-match scoring, and engagement onboarding lifecycle.

Translates corner-design state_machines (engagement) and validations
(no-eligible-VA) instances, plus the difficulty va_match_score instance
(non-linear weighted selection).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_skill_tag_payload, create_virtual_assistant_payload,
    create_client_payload, scope_client_payload, create_engagement_payload,
    activate_engagement_payload, unique_email,
    assert_engagement,
    TEST_USERS, make_client_headers,
)

SM = TEST_USERS["staffing_manager_headers"]


def _skill(api, code):
    return validate_success(api.create_skill_tag(
        create_skill_tag_payload(code=code, name=code.title()), SM), 201)


def _va(api, skill_ids, name, capacity=40, rating=4.0):
    return validate_success(api.create_virtual_assistant(
        create_virtual_assistant_payload(full_name=name, email=unique_email(name.replace(" ", "")),
                                         skill_tag_ids=skill_ids, weekly_capacity_hours=capacity,
                                         rating=rating), SM), 201)


def _scoped_client(api, skill_ids, name="Client"):
    client = validate_success(api.create_client(create_client_payload(company_name=name), SM), 201)
    validate_success(api.scope_client(client["id"],
        scope_client_payload(required_skill_tag_ids=skill_ids),
        make_client_headers(client["id"])), 200)
    return client


# ─── va_match_score (difficulty: combinatorial_formula, instance 2.B) ───────
def test_va_match_score_capacity_cap_clips_higher_rated_candidate(api):
    """PRD §3.3: "The `match_score` is the skill-coverage component weighted by 0.5, plus the rating component weighted by 0.3, plus the capacity component weighted by 0.2, with the weighted sum rounded half-up to four decimal places"
    PRD §3.3: "Capacity contribution is the VA's `weekly_capacity_hours` divided by 40.0, capped at 1.0"

    Design: Difficulty/combinatorial_formula/va_match_score_nonlinear_weighted_selection
    """
    skill = _skill(api, "VIRTUAL_ASSIST")
    va_a = _va(api, [skill["id"]], "Va A", capacity=40, rating=4.0)
    va_b = _va(api, [skill["id"]], "Va B", capacity=20, rating=5.0)
    client = _scoped_client(api, [skill["id"]], "Delta")
    res = api.create_engagement(create_engagement_payload(client["id"]), SM)
    eng = validate_success(res, 201)
    assert_engagement(eng)
    # VA-A: 0.5*1 + 0.3*(4/5) + 0.2*min(1,40/40) = 0.5 + 0.24 + 0.2 = 0.94
    # VA-B: 0.5*1 + 0.3*(5/5) + 0.2*min(1,20/40) = 0.5 + 0.30 + 0.1 = 0.90
    assert eng["va_id"] == va_a["id"], "capacity cap must clip VA-B below VA-A"
    assert eng["match_score"] == pytest.approx(0.94, abs=1e-9)
    assert eng["status"] == "PROPOSED"


def test_va_match_score_selects_highest_and_stamps_proposed(api):
    """PRD §3.3: "The server selects the candidate with the highest `match_score".
    PRD §3.3: "Rating contribution is the VA's `rating` divided by 5.0"

    Design: Difficulty/combinatorial_formula/va_match_score_nonlinear_weighted_selection
    """
    skill = _skill(api, "BOOKKEEPING_MATCH")
    # Single eligible candidate fully covering the skill: full coverage 1.0,
    # rating 5.0 -> 1.0, capacity 40 -> 1.0  =>  0.5 + 0.3 + 0.2 = 1.0
    va = _va(api, [skill["id"]], "Top VA", capacity=40, rating=5.0)
    client = _scoped_client(api, [skill["id"]], "Match Co")
    eng = validate_success(api.create_engagement(create_engagement_payload(client["id"]), SM), 201)
    assert eng["va_id"] == va["id"]
    assert eng["match_score"] == pytest.approx(1.0, abs=1e-9)
    assert eng["status"] == "PROPOSED"


def test_auto_match_no_eligible_va_returns_no_eligible_va(api):
    """PRD §3.3: "If the eligibility set is empty, the proposal is rejected with `ERR_NO_ELIGIBLE_VA"

    Design: Corner/validations/auto_match_no_eligible_va_returns_no_eligible_va
    """
    rare = _skill(api, "RARE_SK")
    other = _skill(api, "OTHER_SK")
    _va(api, [other["id"]], "Va Other")
    client = _scoped_client(api, [rare["id"]], "Nev")
    res = api.create_engagement(create_engagement_payload(client["id"]), SM)
    validate_error(res, "ERR_NO_ELIGIBLE_VA", expected_status=422)


# ─── engagement state machine (corner) ──────────────────────────────────────
def test_reject_proposed_engagement_moves_to_rejected(api):
    """PRD §3.3: "Rejecting** a proposal advances `PROPOSED → REJECTED` and has no further effect"

    Design: Corner/state_machines/reject_proposed_engagement_moves_to_rejected
    """
    skill = _skill(api, "DISPATCH")
    va = _va(api, [skill["id"]], "Va Rj")
    client = _scoped_client(api, [skill["id"]], "Rjc")
    eng = validate_success(api.create_engagement(
        create_engagement_payload(client["id"], va["id"]), SM), 201)
    res = api.reject_engagement(eng["id"], make_client_headers(client["id"]))
    data = validate_success(res, 200)
    assert data["status"] == "REJECTED"


def test_accept_already_accepted_engagement_returns_invalid_state(api):
    """PRD §2.7: "that the target resource is in a state from which the requested transition is defined — `ERR_INVALID_STATE".
    PRD §3.3: "Accepting** a proposal advances `PROPOSED → ONBOARDING` and may only happen while the VA's `status` is `AVAILABLE` or `ENGAGED` (not `BENCHED".

    Design: Corner/state_machines/accept_already_accepted_engagement_returns_invalid_state
    """
    skill = _skill(api, "ONBOARD_SK")
    va = _va(api, [skill["id"]], "Va Ob")
    client = _scoped_client(api, [skill["id"]], "Obc")
    ch = make_client_headers(client["id"])
    eng = validate_success(api.create_engagement(
        create_engagement_payload(client["id"], va["id"]), SM), 201)
    validate_success(api.accept_engagement(eng["id"], ch), 200)
    res = api.accept_engagement(eng["id"], ch)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_return_to_proposed_reverts_onboarding_engagement(api):
    """PRD §3.3: "During onboarding the StaffingManager may **return the engagement to proposed** (`ONBOARDING → PROPOSED`), but only while `onboarding_checklist_done` is still false; if returning leaves the VA holding no other active engagement, the VA reverts to `AVAILABLE"

    Design: Corner/state_machines/return_to_proposed_reverts_onboarding_engagement
    """
    skill = _skill(api, "RTP_SK")
    va = _va(api, [skill["id"]], "Va Rtp")
    client = _scoped_client(api, [skill["id"]], "Rtp")
    ch = make_client_headers(client["id"])
    eng = validate_success(api.create_engagement(
        create_engagement_payload(client["id"], va["id"]), SM), 201)
    validate_success(api.accept_engagement(eng["id"], ch), 200)
    res = api.return_engagement_to_proposed(eng["id"], SM)
    data = validate_success(res, 200)
    assert data["status"] == "PROPOSED"
    va_after = validate_success(api.get_virtual_assistant(va["id"], SM), 200)
    assert va_after["status"] == "AVAILABLE"
