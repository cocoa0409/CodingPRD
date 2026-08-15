"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: Panelist calls are entity-backed by Panelist and Client
calls are entity-backed by ClientAccount. Ownership-gated calls (attribute
scores, request-changes) always build per-instance headers from the real
entity id via the make_* builders; report authoring threads a stable opaque
SensoryScientist id (default "sci-author") and QA review a distinct opaque
QAOfficer id (default "qa-1") so segregation-of-duties checks pass.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import ALL_ATTRIBUTES, DEFAULT_CLOCK_UTC
from .factories import (
    create_arm_payload,
    create_assignment_payload,
    create_chamber_payload,
    create_client_payload,
    create_panelist_payload,
    create_recommendation_payload,
    create_report_payload,
    create_score_payload,
    create_session_payload,
    create_study_payload,
    create_time_point_payload,
    pull_payload,
)
from .test_users import (
    TEST_USERS,
    make_panelist_headers,
    make_qa_headers,
    make_scientist_headers,
)

LD = TEST_USERS["lab_director_headers"]
SCI = TEST_USERS["scientist_headers"]
PC = TEST_USERS["coordinator_headers"]
AN = TEST_USERS["analyst_headers"]

DEFAULT_AUTHOR = "sci-author"
DEFAULT_QA = "qa-1"


# ---------------------------------------------------------------------------
# Tier 0: logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_CLOCK_UTC):
    """Advance the server's logical clock (LabDirector capability)."""
    return get_success_data(api_client.set_clock(to_iso8601, LD))


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_client(name=None, contact_email=None, tier=None, topup_hours=None):
    """Create a client account; optionally top up its retainer. Returns client."""
    overrides = {}
    if name is not None:
        overrides["name"] = name
    if contact_email is not None:
        overrides["contact_email"] = contact_email
    if tier is not None:
        overrides["tier"] = tier
    client = get_success_data(api_client.create_client(create_client_payload(**overrides), LD))
    if topup_hours is not None:
        client = get_success_data(api_client.top_up_retainer(client["id"], topup_hours, LD))
    return client


def top_up(client_id, hours):
    """Add prepaid lab hours to a client's retainer balance."""
    return get_success_data(api_client.top_up_retainer(client_id, hours, LD))


def create_draft_study(client_id, **overrides):
    """Create a study (born DRAFT). Returns the study."""
    return get_success_data(
        api_client.create_study(create_study_payload(client_id, **overrides), SCI))


def add_arm(study_id, packaging_variant="STANDARD_FILM", is_control=True):
    """Add a packaging arm to a DRAFT study. Returns the arm."""
    return get_success_data(api_client.create_study_arm(
        create_arm_payload(study_id, packaging_variant, is_control), SCI))


def add_time_point(study_id, day_index=0):
    """Add a sampling time point (born PENDING). Returns the time point."""
    return get_success_data(api_client.create_time_point(
        create_time_point_payload(study_id, day_index), SCI))


def create_chamber(chamber_code=None, temp_c=20, capacity_units=10):
    """Register a storage chamber (reserved_units 0). Returns the chamber."""
    overrides = {}
    if chamber_code is not None:
        overrides["chamber_code"] = chamber_code
    return get_success_data(api_client.create_chamber(
        create_chamber_payload(temp_c=temp_c, capacity_units=capacity_units,
                               **overrides), LD))


def create_qualified_panelist(full_name=None, email=None, acuity_score=90,
                              qualified_attributes=None):
    """Register a panelist and walk APPLIED -> TRAINING -> QUALIFIED.
    Returns the QUALIFIED panelist."""
    overrides = {"qualified_attributes": qualified_attributes or list(ALL_ATTRIBUTES)}
    if full_name is not None:
        overrides["full_name"] = full_name
    if email is not None:
        overrides["email"] = email
    panelist = get_success_data(
        api_client.create_panelist(create_panelist_payload(**overrides), PC))
    get_success_data(api_client.record_screening(panelist["id"], acuity_score, PC))
    for _ in range(3):
        panelist = get_success_data(api_client.record_training(panelist["id"], PC))
    return panelist


def get_study(study_id):
    return get_success_data(api_client.get_study(study_id, SCI))


def get_client(client_id):
    return get_success_data(api_client.get_client(client_id, LD))


def get_chamber(chamber_id):
    return get_success_data(api_client.get_chamber(chamber_id, LD))


def get_panelist(panelist_id):
    return get_success_data(api_client.get_panelist(panelist_id, PC))


def get_session(session_id):
    return get_success_data(api_client.get_session(session_id, PC))


def get_assignment(assignment_id):
    return get_success_data(api_client.get_assignment(assignment_id, PC))


def get_time_point(time_point_id):
    return get_success_data(api_client.get_time_point(time_point_id, SCI))


def get_recommendation(rec_id):
    return get_success_data(api_client.get_recommendation(rec_id, SCI))


def get_report(report_id):
    return get_success_data(api_client.get_report(report_id, SCI))


def list_sample_units(**params):
    data, _meta = validate_paginated(api_client.list_sample_units(LD, params=params))
    return data


# ---------------------------------------------------------------------------
# Tier 2: study state progression
# ---------------------------------------------------------------------------

def submit_and_approve(study_id):
    """Walk a study DRAFT -> DESIGN_REVIEW -> SCHEDULED. Returns the study."""
    get_success_data(api_client.submit_design(study_id, SCI))
    return get_success_data(api_client.approve_design(study_id, LD))


def activate(study_id):
    """Walk SCHEDULED -> IN_PROGRESS (reserves retainer hours). Returns the study."""
    return get_success_data(api_client.activate_study(study_id, SCI))


def setup_study_in_progress(study_overrides=None, arm_variants=("STANDARD_FILM",),
                            control_index=0, day_indexes=(0,), topup_hours=100,
                            chamber_capacity=10, chamber_temp_c=20,
                            with_chamber=True):
    """Client (topped up) + study + arms + time points (+ chamber), walked to
    IN_PROGRESS. Returns a dict of the created resources."""
    set_clock()
    client = create_client(topup_hours=topup_hours)
    study = create_draft_study(client["id"], **(study_overrides or {}))
    arms = []
    for i, variant in enumerate(arm_variants):
        arms.append(add_arm(study["id"], variant, is_control=(i == control_index)))
    tps = [add_time_point(study["id"], d) for d in day_indexes]
    chamber = create_chamber(temp_c=chamber_temp_c,
                             capacity_units=chamber_capacity) if with_chamber else None
    submit_and_approve(study["id"])
    study = activate(study["id"])
    return {
        "client": get_client(client["id"]),
        "study": study,
        "arms": arms,
        "time_points": tps,
        "chamber": chamber,
    }


def setup_study_in_analysis(study_overrides=None, arm_variants=("STANDARD_FILM",),
                            day_indexes=(0,), topup_hours=100):
    """IN_PROGRESS study whose time points are all SKIPPED, then fieldwork
    closed -> ANALYSIS. No pulls, no sessions. Returns the resource dict."""
    env = setup_study_in_progress(study_overrides=study_overrides,
                                  arm_variants=arm_variants,
                                  day_indexes=day_indexes,
                                  topup_hours=topup_hours,
                                  with_chamber=False)
    for tp in env["time_points"]:
        get_success_data(api_client.skip_time_point(tp["id"], SCI))
    env["study"] = get_success_data(api_client.close_fieldwork(env["study"]["id"], SCI))
    return env


# ---------------------------------------------------------------------------
# Tier 3: sessions, rosters, scoring
# ---------------------------------------------------------------------------

def create_session(study_id, time_point_id, arm_id,
                   scheduled_start_utc="2026-08-01T10:00:00Z",
                   scheduled_end_utc="2026-08-01T11:00:00Z"):
    """Plan an evaluation session (born PLANNED). Returns the session."""
    return get_success_data(api_client.create_session(
        create_session_payload(study_id, time_point_id, arm_id,
                               scheduled_start_utc, scheduled_end_utc), PC))


def assign_panelist(session_id, panelist_id):
    """Assign a QUALIFIED panelist to a PLANNED/OPEN session. Returns the assignment."""
    return get_success_data(api_client.create_assignment(
        create_assignment_payload(session_id, panelist_id), PC))


def pull_units(time_point_id, chamber_id, arm_id, quantity=1,
               unit_purpose="EVALUATION"):
    """Pull sample units from a chamber for one arm. Returns the time point."""
    return get_success_data(api_client.pull_samples(
        time_point_id, pull_payload(chamber_id, arm_id, quantity, unit_purpose), SCI))


def open_session(session_id):
    """PLANNED -> OPEN. Returns the session."""
    return get_success_data(api_client.open_session(session_id, PC))


def lock_session(session_id):
    """OPEN -> LOCKED (computes means/significance/cascades). Returns the session."""
    return get_success_data(api_client.lock_session(session_id, PC))


def analyze_session(session_id):
    """LOCKED -> ANALYZED (final consistency + time-point bubble-up)."""
    return get_success_data(api_client.analyze_session(session_id, SCI))


def submit_all_scores(assignment_id, panelist_id, uniform_score=9, overall_score=None):
    """Record all six attribute scores for an assignment as its owning panelist;
    the sixth distinct attribute flips the assignment to SUBMITTED.
    Returns the refreshed assignment."""
    headers = make_panelist_headers(panelist_id)
    for attribute in ALL_ATTRIBUTES:
        score = overall_score if attribute == "OVERALL" and overall_score is not None \
            else uniform_score
        get_success_data(api_client.create_score(
            create_score_payload(assignment_id, attribute, score), headers))
    return get_assignment(assignment_id)


def run_session_to_analyzed(session, panelist_scores):
    """Open the session (clock must already be inside its window), submit full
    scorecards, lock, analyze. `panelist_scores` is a list of
    (assignment_id, panelist_id, uniform_score, overall_score) tuples.
    Returns the ANALYZED session."""
    open_session(session["id"])
    for assignment_id, panelist_id, uniform, overall in panelist_scores:
        submit_all_scores(assignment_id, panelist_id, uniform, overall)
    lock_session(session["id"])
    return analyze_session(session["id"])


def setup_session_panel(time_points=None, arm_variants=("STANDARD_FILM",),
                        num_panelists=4, chamber_capacity=10, pull_quantity=None,
                        session_windows=None, study_overrides=None,
                        topup_hours=100):
    """IN_PROGRESS study + chamber + pulled EVALUATION units per (time point,
    arm) + one PLANNED session per (time point, arm) + `num_panelists`
    QUALIFIED panelists each assigned to every session.

    - time_points: tuple of day_indexes (default (0,))
    - session_windows: list of (start, end) ISO strings, one per session in
      (time point, arm) order; defaults to same-day hourly slots on day 0.
    Returns dict with env + sessions + panelists + assignments."""
    env = setup_study_in_progress(study_overrides=study_overrides,
                                  arm_variants=arm_variants,
                                  day_indexes=time_points or (0,),
                                  topup_hours=topup_hours,
                                  chamber_capacity=chamber_capacity)
    tps = env["time_points"]
    arms = env["arms"]
    chamber = env["chamber"]
    quantity = pull_quantity if pull_quantity is not None else num_panelists
    for tp in tps:
        for arm in arms:
            pull_units(tp["id"], chamber["id"], arm["id"], quantity=quantity)
    windows = session_windows or [
        (f"2026-08-01T{10 + i:02d}:00:00Z", f"2026-08-01T{11 + i:02d}:00:00Z")
        for i in range(len(tps) * len(arms))
    ]
    sessions = []
    i = 0
    for tp in tps:
        for arm in arms:
            sessions.append(create_session(env["study"]["id"], tp["id"], arm["id"],
                                           *windows[i]))
            i += 1
    panelists = [create_qualified_panelist() for _ in range(num_panelists)]
    assignments = {
        s["id"]: [assign_panelist(s["id"], p["id"]) for p in panelists]
        for s in sessions
    }
    env.update({"sessions": sessions, "panelists": panelists,
                "assignments": assignments})
    return env


# ---------------------------------------------------------------------------
# Tier 4: recommendations, reports, completion
# ---------------------------------------------------------------------------

def propose_recommendation(study_id, arm_id):
    """Propose a date-code recommendation against the study's CURRENT version
    (OCC). Returns the PROPOSED recommendation."""
    study = get_study(study_id)
    return get_success_data(api_client.create_recommendation(
        create_recommendation_payload(study_id, arm_id, study["version"]), SCI))


def propose_and_accept_recommendation(study_id, arm_id):
    """Propose then accept; may auto-advance the study ANALYSIS -> REPORTING.
    Returns the ACCEPTED recommendation."""
    rec = propose_recommendation(study_id, arm_id)
    return get_success_data(api_client.accept_recommendation(rec["id"], SCI))


def setup_reporting_study(arm_variants=("STANDARD_FILM",), study_overrides=None,
                          topup_hours=100):
    """ANALYSIS study (all time points skipped) + one ACCEPTED recommendation
    per arm; the last accept auto-advances the study to REPORTING.
    Returns env dict with study + arms + recs."""
    env = setup_study_in_analysis(study_overrides=study_overrides,
                                  arm_variants=arm_variants,
                                  topup_hours=topup_hours)
    recs = [propose_and_accept_recommendation(env["study"]["id"], arm["id"])
            for arm in env["arms"]]
    env["recommendations"] = recs
    env["study"] = get_study(env["study"]["id"])
    return env


def create_draft_report(study_id, title=None, author=DEFAULT_AUTHOR):
    """Draft a report as the given opaque SensoryScientist id. Returns the report."""
    return get_success_data(api_client.create_report(
        create_report_payload(study_id, title),
        make_scientist_headers(author)))


def attach_and_submit_report(report_id, recommendation_id, author=DEFAULT_AUTHOR):
    """Attach an ACCEPTED recommendation then submit DRAFT -> INTERNAL_REVIEW.
    Returns the submitted report."""
    headers = make_scientist_headers(author)
    get_success_data(api_client.attach_recommendation(report_id, recommendation_id,
                                                      headers))
    return get_success_data(api_client.submit_report(report_id, headers))


def walk_report_to_client_review(report_id, author=DEFAULT_AUTHOR, qa=DEFAULT_QA):
    """INTERNAL_REVIEW -> CLIENT_REVIEW by an independent QAOfficer."""
    return get_success_data(api_client.qa_approve_report(report_id,
                                                         make_qa_headers(qa)))


def setup_client_review_report(arm_variants=("STANDARD_FILM",),
                               study_overrides=None, topup_hours=100,
                               author=DEFAULT_AUTHOR, qa=DEFAULT_QA):
    """REPORTING study + report pinned to the first arm's ACCEPTED
    recommendation + submitted + QA-approved -> CLIENT_REVIEW.
    Returns env dict with report."""
    env = setup_reporting_study(arm_variants=arm_variants,
                                study_overrides=study_overrides,
                                topup_hours=topup_hours)
    report = create_draft_report(env["study"]["id"], author=author)
    attach_and_submit_report(report["id"], env["recommendations"][0]["id"],
                             author=author)
    env["report"] = walk_report_to_client_review(report["id"], author=author, qa=qa)
    return env


def release_report(report_id):
    """CLIENT_REVIEW -> RELEASED (completes the study). Returns the report."""
    return get_success_data(api_client.release_report(report_id, LD))


def setup_completed_study(study_overrides=None, topup_hours=100,
                          chamber_capacity=10):
    """Full lifecycle through report release -> study COMPLETED.
    Pulls 1 EVALUATION + 1 RETAIN unit at tp0, skips tp0 (EVALUATION unit
    discarded, RETAIN preserved), closes fieldwork, accepts the control arm's
    recommendation, releases the report. Returns env dict including the
    surviving RETAIN unit."""
    env = setup_study_in_progress(study_overrides=study_overrides,
                                  arm_variants=("STANDARD_FILM",),
                                  day_indexes=(0,),
                                  topup_hours=topup_hours,
                                  chamber_capacity=chamber_capacity)
    study_id = env["study"]["id"]
    arm_id = env["arms"][0]["id"]
    tp_id = env["time_points"][0]["id"]
    chamber_id = env["chamber"]["id"]
    pull_units(tp_id, chamber_id, arm_id, quantity=1, unit_purpose="EVALUATION")
    pull_units(tp_id, chamber_id, arm_id, quantity=1, unit_purpose="RETAIN")
    get_success_data(api_client.skip_time_point(tp_id, SCI))
    env["study"] = get_success_data(api_client.close_fieldwork(study_id, SCI))
    rec = propose_and_accept_recommendation(study_id, arm_id)
    report = create_draft_report(study_id)
    attach_and_submit_report(report["id"], rec["id"])
    walk_report_to_client_review(report["id"])
    env["recommendation"] = rec
    env["report"] = release_report(report["id"])
    env["study"] = get_study(study_id)
    env["retain_unit"] = [u for u in list_sample_units(study_id=study_id,
                                                       unit_purpose="RETAIN")][0]
    env["client"] = get_client(env["client"]["id"])
    return env
