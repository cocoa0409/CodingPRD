"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "Setup failed" errors rather than confusing assertion failures. Every
helper builds its preconditions from scratch (the server kills and relaunches the
API before each test, so every test starts against an empty database).

Juror is an entity-backed role: a juror submitting a questionnaire or requesting
a disposition must own the summons. Those calls thread make_juror_headers with
the acting Juror.id; the shared juror constant is never used for ownership-gated
calls.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_service_term_payload, create_juror_payload, draw_payload,
    qualification_payload, check_in_payload, disposition_payload, decide_payload,
    create_trial_payload, create_panel_payload, seat_payload, set_clock_payload,
)
from .test_users import TEST_USERS, make_juror_headers


# ─── Header shortcuts ─────────────────────────────────────────────────
_ADMIN = TEST_USERS["jury_administrator_headers"]
_CLERK = TEST_USERS["court_clerk_headers"]
_JUDGE = TEST_USERS["judge_headers"]


# ─── Tier 0: clock ────────────────────────────────────────────────────

def set_clock(to_iso8601):
    """Pin the server clock to a fixed instant (JuryAdministrator capability)."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), _ADMIN))


# ─── Tier 1: primitive creates ────────────────────────────────────────

def create_term(**overrides):
    """Create a DRAFT service term. Returns the term object."""
    return get_success_data(api_client.create_service_term(create_service_term_payload(**overrides), _ADMIN))


def add_juror(term_id, **overrides):
    """Add a PENDING juror to a term pool. Returns the juror object."""
    return get_success_data(api_client.create_juror(term_id, create_juror_payload(**overrides), _ADMIN))


def admin_qualify(juror_id):
    """Admin override PENDING -> QUALIFIED. Returns the juror object."""
    return get_success_data(api_client.qualify_juror(juror_id, _ADMIN))


def open_term(term_id):
    """Open a DRAFT term -> OPEN. Returns the term object (carries new version)."""
    return get_success_data(api_client.open_service_term(term_id, _ADMIN))


def get_term(term_id):
    return get_success_data(api_client.get_service_term(term_id, _ADMIN))


def get_summons(summons_id):
    return get_success_data(api_client.get_summons(summons_id, _CLERK))


def get_juror(juror_id):
    return get_success_data(api_client.get_juror(juror_id, _ADMIN))


def get_panel(panel_id):
    return get_success_data(api_client.get_panel(panel_id, _JUDGE))


# ─── Tier 2: pool / draw composites ───────────────────────────────────

def setup_open_term_with_qualified_jurors(num_jurors=1, term_overrides=None,
                                          juror_overrides=None):
    """Create a term, add `num_jurors` admin-qualified jurors, and OPEN it.

    Returns (term, [jurors], open_version). The open_version is the term.version
    immediately after opening — the value a first draw must carry as
    expected_service_term_version.
    """
    term = create_term(**(term_overrides or {}))
    jurors = []
    for i in range(num_jurors):
        ov = dict(juror_overrides or {})
        ov.setdefault("full_name", f"Juror {i + 1}")
        jurors.append(add_juror(term["id"], **ov))
    for j in jurors:
        admin_qualify(j["id"])
    opened = open_term(term["id"])
    return term, jurors, opened["version"]


def draw(term_id, expected_version, count=1):
    """Draw `count` summonses (JuryAdministrator-exclusive). Returns the list."""
    return get_success_data(api_client.draw(term_id, draw_payload(count, expected_version), _ADMIN))


def setup_summoned(term_overrides=None, juror_overrides=None):
    """Open term + one qualified juror + one drawn SUMMONED summons.

    Returns dict(term, juror, summons, term_version_after_draw).
    """
    term, jurors, open_v = setup_open_term_with_qualified_jurors(
        num_jurors=1, term_overrides=term_overrides, juror_overrides=juror_overrides
    )
    juror = jurors[0]
    summonses = draw(term["id"], open_v, count=1)
    summons = summonses[0]
    after = get_term(term["id"])
    return {
        "term": term,
        "juror": juror,
        "summons": summons,
        "term_version_after_draw": after["version"],
    }


def submit_qualifying_questionnaire(summons_id, juror_id, **answer_overrides):
    """Juror submits a passing questionnaire on their own summons (ownership-gated)."""
    return get_success_data(
        api_client.submit_qualification(
            summons_id, qualification_payload(**answer_overrides), make_juror_headers(juror_id)
        )
    )


def setup_qualified_pending(term_overrides=None, juror_overrides=None):
    """Open term + qualified juror + drawn summons advanced to QUALIFIED_PENDING
    via a passing questionnaire.

    Returns dict(term, juror, summons, term_version_after_draw).
    """
    s = setup_summoned(term_overrides=term_overrides, juror_overrides=juror_overrides)
    submit_qualifying_questionnaire(s["summons"]["id"], s["juror"]["id"])
    return s


# ─── Tier 3: reporting / check-in composites ──────────────────────────

def check_in(summons_id, service_date, on_floor_hours):
    """Record a check-in (CourtClerk). Returns the check-in object."""
    return get_success_data(
        api_client.check_in(summons_id, check_in_payload(service_date, on_floor_hours), _CLERK)
    )


def setup_reporting(report_date="2026-07-01T00:00:00Z", clock="2026-07-01T08:00:00Z",
                    first_service_date="2026-07-01T00:00:00Z", on_floor_hours=8.0,
                    term_overrides=None, juror_overrides=None):
    """Open term + qualified juror + QUALIFIED_PENDING summons + one check-in →
    summons in REPORTING.

    Returns dict(term, juror, summons, term_version_after_draw, check_in).
    """
    set_clock(clock)
    to = dict(term_overrides or {})
    to.setdefault("report_date", report_date)
    s = setup_qualified_pending(term_overrides=to, juror_overrides=juror_overrides)
    ci = check_in(s["summons"]["id"], first_service_date, on_floor_hours)
    s["check_in"] = ci
    return s


# ─── Tier 4: trial / panel / seat composites ──────────────────────────

def create_ready_trial(term_id, required_jurors=1, caption=None):
    """Create a trial under a term and ready it. Returns the trial object (READY)."""
    trial = get_success_data(
        api_client.create_trial(term_id, create_trial_payload(caption=caption, required_jurors=required_jurors), _JUDGE)
    )
    return get_success_data(api_client.ready_trial(trial["id"], _JUDGE))


def create_panel(trial_id, target_size=None):
    """Create a FORMING panel for a trial. Returns the panel object (version 1)."""
    return get_success_data(api_client.create_panel(trial_id, create_panel_payload(target_size=target_size), _JUDGE))


def seat(panel_id, summons_id, expected_panel_version):
    """Seat a REPORTING summons. Returns the panel assignment object."""
    return get_success_data(
        api_client.seat(panel_id, seat_payload(summons_id, expected_panel_version), _JUDGE)
    )


def setup_reporting_with_forming_panel(target_size=2, required_jurors=2,
                                       report_date="2026-07-01T00:00:00Z",
                                       clock="2026-07-10T08:00:00Z",
                                       service_date="2026-07-10T00:00:00Z"):
    """Open term + REPORTING summons + READY trial + FORMING panel (no seat yet).

    Returns dict with term, juror, summons, trial, panel, panel_version, plus
    term_version_after_draw.
    """
    s = setup_reporting(report_date=report_date, clock=clock,
                        first_service_date=service_date)
    trial = create_ready_trial(s["term"]["id"], required_jurors=required_jurors)
    panel = create_panel(trial["id"], target_size=target_size)
    s["trial"] = trial
    s["panel"] = panel
    s["panel_version"] = panel["version"]
    return s


def setup_seated(target_size=2, required_jurors=2,
                 report_date="2026-07-01T00:00:00Z",
                 clock="2026-07-10T08:00:00Z",
                 service_date="2026-07-10T00:00:00Z"):
    """Open term + REPORTING summons + READY trial + FORMING panel + first seat
    landed (panel still FORMING when target_size >= 2).

    Returns dict with term, juror, summons, trial, panel, assignment, and the
    post-seat panel object/version (re-fetched).
    """
    s = setup_reporting_with_forming_panel(
        target_size=target_size, required_jurors=required_jurors,
        report_date=report_date, clock=clock, service_date=service_date,
    )
    assignment = seat(s["panel"]["id"], s["summons"]["id"], s["panel_version"])
    panel_after = get_panel(s["panel"]["id"])
    s["assignment"] = assignment
    s["panel_after_seat"] = panel_after
    s["panel_version_after_seat"] = panel_after["version"]
    return s


# ─── Tier 5: disposition composites ───────────────────────────────────

def request_disposition(summons_id, juror_id, kind, reason_code, requested_term_id=None):
    """Juror requests a disposition on their own summons (ownership-gated)."""
    return get_success_data(
        api_client.create_disposition(
            summons_id,
            disposition_payload(kind, reason_code, requested_term_id=requested_term_id),
            make_juror_headers(juror_id),
        )
    )


def decide(disposition_id, decision, headers):
    """Decide a disposition. headers chooses the deciding office."""
    return get_success_data(api_client.decide_disposition(disposition_id, decide_payload(decision), headers))


def setup_pending_defer(report_date="2026-07-01T00:00:00Z",
                        next_report_date="2026-10-01T00:00:00Z"):
    """Open term + QUALIFIED_PENDING summons + a DRAFT next term + a PENDING DEFER
    disposition targeting the next term.

    Returns dict(term, next_term, juror, summons, disposition).
    """
    term = create_term(report_date=report_date, name="Term A")
    next_term = create_term(report_date=next_report_date, name="Term A-next")
    juror = add_juror(term["id"], full_name="Defer Juror")
    admin_qualify(juror["id"])
    open_v = open_term(term["id"])["version"]
    summonses = draw(term["id"], open_v, count=1)
    summons = summonses[0]
    submit_qualifying_questionnaire(summons["id"], juror["id"])
    disp = request_disposition(summons["id"], juror["id"], "DEFER", "HARDSHIP",
                               requested_term_id=next_term["id"])
    return {
        "term": term,
        "next_term": next_term,
        "juror": juror,
        "summons": summons,
        "disposition": disp,
    }


def setup_pending_excuse(kind="EXCUSE", reason_code="MEDICAL"):
    """Open term + QUALIFIED_PENDING summons + a PENDING EXCUSE/EXEMPT disposition.

    Returns dict(term, juror, summons, disposition).
    """
    s = setup_qualified_pending()
    disp = request_disposition(s["summons"]["id"], s["juror"]["id"], kind, reason_code)
    s["disposition"] = disp
    return s
