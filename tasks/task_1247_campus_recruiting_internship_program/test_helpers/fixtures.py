"""Composite setup helpers.

Every fixture builds its preconditions from scratch against an empty database
(the harness restarts the server before every test), using only PRD-declared
endpoints. Setup calls use the lenient get_success_data() validator so a
failed precondition surfaces as a clear "Setup failed" message.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as _api
from .factories import (
    create_season_payload,
    create_school_target_payload,
    create_campus_event_payload,
    create_candidate_payload,
    create_application_payload,
    create_employee_payload,
    create_interview_day_payload,
    create_interview_slot_payload,
    create_evaluation_payload,
    create_offer_payload,
    create_intern_project_payload,
)
from .test_users import (
    make_admin_headers,
    make_recruiter_headers,
    make_candidate_headers,
    make_evaluator_headers,
    make_mentor_headers,
    make_anonymous_headers,
)

ADMIN = make_admin_headers()
RECRUITER = make_recruiter_headers()
ANON = make_anonymous_headers()


class Ctx(dict):
    """Attribute-access dict used as a fixture result bag."""

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError:
            raise AttributeError(item)


def _setup_fail(msg, resp):
    raise AssertionError(f"Setup failed: {msg} -> HTTP {resp.status_code}: {resp.text}")


# ---------------------------------------------------------------------------
# Tier 1: Season + school scaffolding
# ---------------------------------------------------------------------------

def create_season(admin_headers=ADMIN, **overrides):
    resp = _api.create_season(create_season_payload(**overrides), admin_headers)
    if resp.status_code != 201:
        _setup_fail("create season", resp)
    return get_success_data(resp)


def create_school(season_id, admin_headers=ADMIN, **overrides):
    resp = _api.create_school_target(
        season_id, create_school_target_payload(**overrides), admin_headers,
    )
    if resp.status_code != 201:
        _setup_fail("create school target", resp)
    return get_success_data(resp)


def advance_season(season_id, admin_headers=ADMIN):
    resp = _api.advance_season(season_id, admin_headers)
    if resp.status_code != 200:
        _setup_fail(f"advance season {season_id}", resp)
    return get_success_data(resp)


def set_clock(to_iso8601, admin_headers=ADMIN):
    resp = _api.set_clock(to_iso8601, admin_headers)
    if resp.status_code != 200:
        _setup_fail(f"set clock {to_iso8601}", resp)
    return get_success_data(resp)


def create_candidate(email="a@x.com", full_name="Candidate A", headers=ANON):
    resp = _api.create_candidate(
        create_candidate_payload(email=email, full_name=full_name), headers,
    )
    if resp.status_code != 201:
        _setup_fail("create candidate", resp)
    return get_success_data(resp)


def submit_application(season_id, candidate_id, school_target_id, **overrides):
    payload = create_application_payload(
        candidate_id=candidate_id, school_target_id=school_target_id, **overrides,
    )
    resp = _api.create_application(
        season_id, payload, make_candidate_headers(candidate_id),
    )
    if resp.status_code != 201:
        _setup_fail("submit application", resp)
    return get_success_data(resp)


def create_employee(season_id, admin_headers=ADMIN, **overrides):
    resp = _api.create_employee(
        season_id, create_employee_payload(**overrides), admin_headers,
    )
    if resp.status_code != 201:
        _setup_fail("create employee", resp)
    return get_success_data(resp)


def create_completed_event(season_id, school_target_id, start_at, end_at,
                           event_type="RESUME_DROP", resume_count=10,
                           headers=RECRUITER):
    """Create a campus event and immediately complete it (feeds screening)."""
    resp = _api.create_campus_event(
        season_id,
        create_campus_event_payload(
            school_target_id=school_target_id, event_type=event_type,
            start_at=start_at, end_at=end_at,
        ),
        headers,
    )
    if resp.status_code != 201:
        _setup_fail("create campus event", resp)
    event = get_success_data(resp)
    resp = _api.complete_campus_event(event["id"], resume_count, headers)
    if resp.status_code != 200:
        _setup_fail("complete campus event", resp)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: Season at a target epoch with one application at a target status
# ---------------------------------------------------------------------------

def setup_open_season_with_application(**season_overrides):
    """Season OPEN; one SUBMITTED application; clock at 2026-05-15.

    Returns Ctx(season, school, candidate, application).
    """
    season_overrides.setdefault("shortlist_score_threshold", 10)
    season = create_season(**season_overrides)
    school = create_school(season["id"])
    advance_season(season["id"])
    set_clock("2026-05-15T00:00:00Z")
    candidate = create_candidate()
    application = submit_application(season["id"], candidate["id"], school["id"])
    return Ctx(season=season, school=school, candidate=candidate,
               application=application)


def setup_selection_with_shortlisted(**season_overrides):
    """Season SELECTION; one SHORTLISTED application; clock at 2026-05-21.

    Returns Ctx(season, school, candidate, application).
    """
    ctx = setup_open_season_with_application(**season_overrides)
    set_clock("2026-05-21T00:00:00Z")
    advance_season(ctx.season["id"])
    resp = _api.screen_application(ctx.application["id"], "SHORTLIST", RECRUITER)
    if resp.status_code != 200:
        _setup_fail("screen application SHORTLIST", resp)
    ctx.application = get_success_data(resp)
    return ctx


def setup_selection_with_day_and_evaluator(shortlist_overrides=None,
                                           day_overrides=None,
                                           employee_overrides=None):
    """Season SELECTION; SHORTLISTED application; employee; interview day.

    Returns Ctx(season, school, candidate, application, evaluator, day).
    """
    ctx = setup_selection_with_shortlisted(**(shortlist_overrides or {}))
    ctx.evaluator = create_employee(ctx.season["id"], **(employee_overrides or {}))
    resp = _api.create_interview_day(
        ctx.season["id"], create_interview_day_payload(**(day_overrides or {})),
        RECRUITER,
    )
    if resp.status_code != 201:
        _setup_fail("create interview day", resp)
    ctx.day = get_success_data(resp)
    return ctx


def setup_interview_scheduled(shortlist_overrides=None, day_overrides=None,
                              employee_overrides=None, slot_overrides=None):
    """Season SELECTION; application INTERVIEW_SCHEDULED with one BOOKED slot.

    Returns Ctx(..., evaluator, day, slot).
    """
    ctx = setup_selection_with_day_and_evaluator(
        shortlist_overrides, day_overrides, employee_overrides,
    )
    payload = create_interview_slot_payload(
        application_id=ctx.application["id"], evaluator_id=ctx.evaluator["id"],
        **(slot_overrides or {}),
    )
    resp = _api.book_interview_slot(ctx.day["id"], payload, RECRUITER)
    if resp.status_code != 201:
        _setup_fail("book interview slot", resp)
    ctx.slot = get_success_data(resp)
    return ctx


def setup_decision_pending(shortlist_overrides=None, employee_overrides=None,
                           evaluation_overrides=None, slot_overrides=None):
    """Season SELECTION; application DECISION_PENDING (one COMPLETED slot).

    Returns Ctx(..., evaluator, day, slot, evaluation).
    """
    ctx = setup_interview_scheduled(
        shortlist_overrides=shortlist_overrides,
        employee_overrides=employee_overrides,
        slot_overrides=slot_overrides,
    )
    payload = create_evaluation_payload(**(evaluation_overrides or {}))
    resp = _api.submit_evaluation(
        ctx.slot["id"], payload, make_evaluator_headers(ctx.evaluator["id"]),
    )
    if resp.status_code != 201:
        _setup_fail("submit evaluation", resp)
    ctx.evaluation = get_success_data(resp)
    resp = _api.get_application(ctx.application["id"], RECRUITER)
    ctx.application = get_success_data(resp)
    return ctx


def setup_offer_period_with_draft_offer(shortlist_overrides=None,
                                        offer_overrides=None,
                                        evaluation_overrides=None,
                                        employee_overrides=None):
    """Season OFFER_PERIOD; application DECISION_PENDING; offer DRAFT.

    Returns Ctx(..., evaluator, day, slot, evaluation, offer).
    """
    ctx = setup_decision_pending(
        shortlist_overrides=shortlist_overrides,
        evaluation_overrides=evaluation_overrides,
        employee_overrides=employee_overrides,
    )
    advance_season(ctx.season["id"])
    resp = _api.create_offer(
        ctx.application["id"], create_offer_payload(**(offer_overrides or {})),
        RECRUITER,
    )
    if resp.status_code != 201:
        _setup_fail("create offer", resp)
    ctx.offer = get_success_data(resp)
    return ctx


def setup_extended_offer(extend_at="2026-07-06T10:00:00Z",
                         shortlist_overrides=None, offer_overrides=None,
                         evaluation_overrides=None, employee_overrides=None):
    """Season OFFER_PERIOD; application OFFER_PENDING; offer EXTENDED.

    Returns Ctx(..., evaluator, day, slot, evaluation, offer).
    """
    ctx = setup_offer_period_with_draft_offer(
        shortlist_overrides=shortlist_overrides,
        offer_overrides=offer_overrides,
        evaluation_overrides=evaluation_overrides,
        employee_overrides=employee_overrides,
    )
    set_clock(extend_at)
    resp = _api.extend_offer(ctx.offer["id"], RECRUITER)
    if resp.status_code != 200:
        _setup_fail("extend offer", resp)
    ctx.offer = get_success_data(resp)
    return ctx


def setup_accepted_offer(extend_at="2026-07-06T10:00:00Z",
                         shortlist_overrides=None, offer_overrides=None,
                         evaluation_overrides=None, employee_overrides=None):
    """Season OFFER_PERIOD; application ACCEPTED; offer ACCEPTED.

    Returns Ctx(..., evaluator, day, slot, evaluation, offer).
    """
    ctx = setup_extended_offer(
        extend_at=extend_at,
        shortlist_overrides=shortlist_overrides,
        offer_overrides=offer_overrides,
        evaluation_overrides=evaluation_overrides,
        employee_overrides=employee_overrides,
    )
    resp = _api.accept_offer(
        ctx.offer["id"], make_candidate_headers(ctx.candidate["id"]),
    )
    if resp.status_code != 200:
        _setup_fail("accept offer", resp)
    ctx.offer = get_success_data(resp)
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: Intern-phase lifecycle (assignment ACTIVE, evaluations, completion)
# ---------------------------------------------------------------------------

def setup_intern_active_with_assignment(shortlist_overrides=None,
                                        offer_overrides=None,
                                        evaluation_overrides=None,
                                        mentor_overrides=None,
                                        project_overrides=None):
    """Season INTERN_ACTIVE; one ACCEPTED application; project OPEN;
    assignment ACTIVE with a mentor distinct from the evaluator.

    Returns Ctx(..., evaluator, mentor, day, slot, evaluation, offer, project,
    assignment).
    """
    ctx = setup_accepted_offer(
        shortlist_overrides=shortlist_overrides,
        offer_overrides=offer_overrides,
        evaluation_overrides=evaluation_overrides,
    )
    ctx.mentor = create_employee(
        ctx.season["id"],
        **(mentor_overrides or {"full_name": "Moe", "email": "moe@co.com"}),
    )
    advance_season(ctx.season["id"])
    resp = _api.create_intern_project(
        ctx.season["id"], create_intern_project_payload(**(project_overrides or {})),
        RECRUITER,
    )
    if resp.status_code != 201:
        _setup_fail("create intern project", resp)
    ctx.project = get_success_data(resp)
    resp = _api.create_project_assignment(
        ctx.project["id"],
        {"application_id": ctx.application["id"], "mentor_id": ctx.mentor["id"]},
        RECRUITER,
    )
    if resp.status_code != 201:
        _setup_fail("create project assignment", resp)
    ctx.assignment = get_success_data(resp)
    return ctx


def submit_intern_eval(assignment_id, mentor_id, eval_type="MID", rating=4,
                       would_rehire=True):
    resp = _api.submit_intern_evaluation(
        assignment_id,
        {"eval_type": eval_type, "rating": rating, "would_rehire": would_rehire},
        make_mentor_headers(mentor_id),
    )
    if resp.status_code != 201:
        _setup_fail(f"submit intern evaluation {eval_type}", resp)
    return get_success_data(resp)


def setup_assignment_with_evals(mid_rating=4, final_rating=4,
                                mid_rehire=True, final_rehire=True,
                                **kwargs):
    """Assignment ACTIVE with MID and FINAL intern evaluations submitted.

    Returns Ctx(..., mid_eval, final_eval).
    """
    ctx = setup_intern_active_with_assignment(**kwargs)
    ctx.mid_eval = submit_intern_eval(
        ctx.assignment["id"], ctx.mentor["id"], "MID", mid_rating, mid_rehire,
    )
    ctx.final_eval = submit_intern_eval(
        ctx.assignment["id"], ctx.mentor["id"], "FINAL", final_rating, final_rehire,
    )
    resp = _api.get_project_assignment(ctx.assignment["id"], RECRUITER)
    ctx.assignment = get_success_data(resp)
    return ctx


def get_offer_disbursement(offer_id, headers=RECRUITER):
    resp = _api.list_offer_disbursements(offer_id, headers)
    if resp.status_code != 200:
        _setup_fail("list offer disbursements", resp)
    data = get_success_data(resp)
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one disbursement for offer {offer_id}"
    )
    return data[0]
