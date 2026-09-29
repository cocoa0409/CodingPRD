"""Composite setup helpers.

Most interesting behaviour in this API only becomes observable after a long
preamble: a school, an intersection with pedestrian crash history, a warrant
study counted and finalized onto that intersection, a certified guard with
complete equipment, an activated post and an assignment. These helpers build
those chains once so tests can concentrate on the trigger and the assertions.

Setup calls use the lenient `get_success_data` validator so a broken preamble
reports "Setup step failed" rather than a confusing assertion deep in a test.
"""
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    certify_guard_payload,
    create_absence_report_payload,
    create_assignment_payload,
    create_complaint_payload,
    create_count_session_payload,
    create_crash_record_payload,
    create_equipment_payload,
    create_grant_program_payload,
    create_guard_payload,
    create_guard_post_payload,
    create_intersection_payload,
    create_mode_share_survey_payload,
    create_project_payload,
    create_school_payload,
    create_training_payload,
    create_walking_route_payload,
    create_warrant_study_payload,
    fund_project_payload,
    offer_response_payload,
    rescind_absence_payload,
    route_segment,
    triage_complaint_payload,
    withdraw_funding_payload,
)
from .test_users import (
    TEST_USERS,
    make_crossing_guard_headers,
    make_school_liaison_headers,
    make_traffic_engineer_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
ENGINEER = TEST_USERS["traffic_engineer_headers"]
SECOND_ENGINEER = TEST_USERS["second_traffic_engineer_headers"]
SUPERVISOR = TEST_USERS["crossing_supervisor_headers"]
REPORTER = TEST_USERS["public_reporter_headers"]

# The count sessions that drive the canonical warrant score of 66.19 at an
# UNCONTROLLED 30 mph intersection carrying two pedestrian crashes.
CANONICAL_AM_SESSION = {
    "session_date": "2026-09-08",
    "period": "AM_ARRIVAL",
    "observed_minutes": 60,
    "child_count": 70,
    "adult_count": 10,
    "vehicle_count": 500,
    "adequate_gaps": 28,
}
CANONICAL_PM_SESSION = {
    "session_date": "2026-09-09",
    "period": "PM_DISMISSAL",
    "observed_minutes": 60,
    "child_count": 50,
    "adult_count": 8,
    "vehicle_count": 380,
    "adequate_gaps": 20,
}
CANONICAL_CRASHES = [
    {"crash_date": "2023-10-01", "severity": "INJURY",
     "involved_pedestrian": True, "involved_school_age": True},
    {"crash_date": "2025-05-14", "severity": "SEVERE_INJURY",
     "involved_pedestrian": True, "involved_school_age": True},
]
EQUIPMENT_ITEM_TYPES = ["HIGH_VIS_VEST", "STOP_PADDLE", "WHISTLE"]


# ----------------------------------------------------------------------
# Clock
# ----------------------------------------------------------------------
def advance_clock(to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock forward and run the assignment checkpoint sweep."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ----------------------------------------------------------------------
# Tier 1: single-resource creation
# ----------------------------------------------------------------------
def create_school(**overrides) -> Dict[str, Any]:
    """Register the canonical school (session 2026-08-24 -> 2027-06-11)."""
    return get_success_data(
        api_client.create_school(create_school_payload(**overrides), ADMIN))


def create_intersection(school_id: str, **overrides) -> Dict[str, Any]:
    """Register an intersection under a school. Defaults to UNCONTROLLED 30 mph."""
    return get_success_data(api_client.create_intersection(
        create_intersection_payload(school_id, **overrides), ADMIN))


def add_crash_records(intersection_id: str,
                      crashes: Optional[List[Dict[str, Any]]] = None
                      ) -> Dict[str, Any]:
    """Append crash records one at a time. Returns the last intersection state,
    whose `version` is the one a warrant study must declare."""
    records = CANONICAL_CRASHES if crashes is None else crashes
    latest: Dict[str, Any] = get_success_data(
        api_client.get_intersection(intersection_id, ADMIN))
    for record in records:
        latest = get_success_data(api_client.create_crash_record(
            intersection_id, create_crash_record_payload(**record), ENGINEER))
    return latest


def create_guard(full_name: str = "Rita Alvarez", home_zone_code: str = "Z-NORTH",
                 hire_date: str = "2026-08-03",
                 substitute_pool_optin: Optional[bool] = None) -> Dict[str, Any]:
    """Enroll a guard applicant. A new guard starts APPLICANT with no equipment."""
    payload = create_guard_payload(full_name=full_name,
                                   home_zone_code=home_zone_code,
                                   hire_date=hire_date)
    if substitute_pool_optin is not None:
        payload["substitute_pool_optin"] = substitute_pool_optin
    return get_success_data(api_client.create_guard(payload, SUPERVISOR))


def issue_full_equipment(guard_id: str, issued_on: str = "2026-08-06") -> Dict[str, Any]:
    """Issue all three required item types so `equipment_complete` becomes true."""
    latest: Dict[str, Any] = {}
    for item_type in EQUIPMENT_ITEM_TYPES:
        latest = get_success_data(api_client.issue_equipment(
            guard_id, create_equipment_payload(item_type, issued_on=issued_on),
            SUPERVISOR))
    return latest


def record_training(guard_id: str, hours: float = 12.0,
                    training_date: str = "2026-08-05",
                    curriculum_code: str = "SRTS-BASIC") -> Dict[str, Any]:
    return get_success_data(api_client.record_training(
        guard_id,
        create_training_payload(hours=hours, training_date=training_date,
                                curriculum_code=curriculum_code),
        SUPERVISOR))


def create_grant_program(total_cents: int = 4_000_000, **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_grant_program(
        create_grant_program_payload(total_cents=total_cents, **overrides), ADMIN))


# ----------------------------------------------------------------------
# Tier 2/3: warrant-study lifecycle shortcuts
# ----------------------------------------------------------------------
def open_warrant_study(intersection_id: str, expected_intersection_version: int,
                       count_window_start: str = "2026-09-08",
                       count_window_end: str = "2026-09-30",
                       author_headers: Optional[Dict[str, str]] = None
                       ) -> Dict[str, Any]:
    """Open a study over a count window. The declared intersection version must
    be the version the intersection currently carries."""
    return get_success_data(api_client.create_warrant_study(
        create_warrant_study_payload(
            intersection_id, expected_intersection_version,
            count_window_start=count_window_start,
            count_window_end=count_window_end),
        author_headers or ENGINEER))


def record_count_session(study_id: str, session: Dict[str, Any],
                         author_headers: Optional[Dict[str, str]] = None
                         ) -> Dict[str, Any]:
    return get_success_data(api_client.create_count_session(
        study_id, create_count_session_payload(**session),
        author_headers or ENGINEER))


def setup_study_ready_to_analyze(
        control_type: str = "UNCONTROLLED",
        speed_limit_mph: int = 30,
        lanes_crossed: int = 2,
        crashes: Optional[List[Dict[str, Any]]] = None,
        sessions: Optional[List[Dict[str, Any]]] = None,
        school: Optional[Dict[str, Any]] = None,
        cross_streets: str = "Maple St & 3rd Ave",
        count_window_start: str = "2026-09-08",
        count_window_end: str = "2026-09-30",
        **school_overrides) -> Dict[str, Any]:
    """School + intersection + crash history + a COUNTING study holding one AM
    and one PM session. Returns {"school", "intersection", "study"}."""
    school = school or create_school(**school_overrides)
    intersection = create_intersection(
        school["id"], control_type=control_type, speed_limit_mph=speed_limit_mph,
        lanes_crossed=lanes_crossed, cross_streets=cross_streets)
    intersection = add_crash_records(intersection["id"], crashes)
    study = open_warrant_study(intersection["id"], intersection["version"],
                               count_window_start=count_window_start,
                               count_window_end=count_window_end)
    for session in (sessions if sessions is not None
                    else [CANONICAL_AM_SESSION, CANONICAL_PM_SESSION]):
        study = record_count_session(study["id"], session)
    return {"school": school, "intersection": intersection, "study": study}


def setup_analyzed_study(**kwargs) -> Dict[str, Any]:
    """As `setup_study_ready_to_analyze`, then analyze. The study carries its
    `scoring_variant`, `warrant_score` and `determination`."""
    scenario = setup_study_ready_to_analyze(**kwargs)
    scenario["study"] = get_success_data(
        api_client.analyze_warrant_study(scenario["study"]["id"], ENGINEER))
    return scenario


def setup_finalized_study(**kwargs) -> Dict[str, Any]:
    """As `setup_analyzed_study`, then finalize as a second engineer so the
    segregation-of-duties rule is satisfied, and re-read the intersection."""
    scenario = setup_analyzed_study(**kwargs)
    scenario["study"] = get_success_data(api_client.finalize_warrant_study(
        scenario["study"]["id"], SECOND_ENGINEER,
        {"engineer_note": "Adopt the recorded determination."}))
    scenario["intersection"] = get_success_data(
        api_client.get_intersection(scenario["intersection"]["id"], ADMIN))
    scenario["school"] = get_success_data(
        api_client.get_school(scenario["school"]["id"], ADMIN))
    return scenario


def setup_warranted_intersection(**kwargs) -> Dict[str, Any]:
    """The canonical WARRANTED intersection: UNCONTROLLED, 30 mph, two
    pedestrian crashes, warrant score 66.19."""
    return setup_finalized_study(**kwargs)


def setup_conditional_intersection(school: Optional[Dict[str, Any]] = None,
                                   **kwargs) -> Dict[str, Any]:
    """A CONDITIONAL intersection: a STOP_SIGN control at 30 mph over the same
    counts scores 51.98, which is under the 60.00 warrant threshold but at or
    above 40.00 with pedestrian crash history on record."""
    return setup_finalized_study(control_type="STOP_SIGN", school=school,
                                 cross_streets="Birch St & 4th Ave", **kwargs)


# ----------------------------------------------------------------------
# Tier 3: guard certification and post staffing shortcuts
# ----------------------------------------------------------------------
def setup_certified_guard(full_name: str = "Rita Alvarez",
                          home_zone_code: str = "Z-NORTH",
                          hire_date: str = "2026-08-03",
                          training_hours: float = 12.0,
                          certified_on: str = "2026-08-07",
                          certification_expires_on: str = "2027-06-30",
                          substitute_pool_optin: Optional[bool] = None
                          ) -> Dict[str, Any]:
    """Enroll a guard, record training hours, issue all three equipment items and
    certify. Returns the CERTIFIED guard."""
    guard = create_guard(full_name=full_name, home_zone_code=home_zone_code,
                         hire_date=hire_date,
                         substitute_pool_optin=substitute_pool_optin)
    record_training(guard["id"], hours=training_hours)
    issue_full_equipment(guard["id"])
    return get_success_data(api_client.certify_guard(
        guard["id"],
        certify_guard_payload(certified_on=certified_on,
                              certification_expires_on=certification_expires_on),
        SUPERVISOR))


def setup_guard_in_training(full_name: str = "Rita Alvarez",
                            home_zone_code: str = "Z-NORTH",
                            training_hours: float = 12.0,
                            with_equipment: bool = True) -> Dict[str, Any]:
    """A guard who has logged training hours and (optionally) full equipment but
    has never been certified, so `certification_status` is IN_TRAINING."""
    guard = create_guard(full_name=full_name, home_zone_code=home_zone_code)
    guard = record_training(guard["id"], hours=training_hours)
    if with_equipment:
        guard = issue_full_equipment(guard["id"])
    return guard


def create_active_post(intersection_id: str, post_label: str = "Maple NW corner",
                       zone_code: str = "Z-NORTH",
                       required_shift: str = "AM") -> Dict[str, Any]:
    """Propose a post and activate it. Returns the ACTIVE post, whose `version`
    is the token an assignment must declare."""
    post = get_success_data(api_client.create_guard_post(
        create_guard_post_payload(intersection_id, post_label=post_label,
                                  zone_code=zone_code,
                                  required_shift=required_shift),
        SUPERVISOR))
    return get_success_data(api_client.activate_guard_post(post["id"], ADMIN))


def create_assignment(post: Dict[str, Any], guard_id: str,
                      start_date: str = "2026-09-08",
                      end_date: str = "2026-09-18") -> Dict[str, Any]:
    """Assign a guard to an ACTIVE post, declaring the post's current version."""
    return get_success_data(api_client.create_assignment(
        post["id"],
        create_assignment_payload(guard_id, post["version"],
                                  start_date=start_date, end_date=end_date),
        SUPERVISOR))


def setup_staffed_post(required_shift: str = "AM",
                       post_label: str = "Maple NW corner",
                       zone_code: str = "Z-NORTH",
                       guard_name: str = "Rita Alvarez",
                       guard_zone: str = "Z-NORTH",
                       substitute_pool_optin: Optional[bool] = None,
                       certification_expires_on: str = "2027-06-30",
                       start_date: str = "2026-09-08",
                       end_date: str = "2026-09-18",
                       scenario: Optional[Dict[str, Any]] = None,
                       **study_kwargs) -> Dict[str, Any]:
    """The workhorse composite: a WARRANTED intersection, an ACTIVE post on it,
    a CERTIFIED guard and a SCHEDULED assignment joining them.

    Returns {"school", "intersection", "study", "guard", "post", "assignment"}.
    """
    scenario = dict(scenario) if scenario else setup_warranted_intersection(
        **study_kwargs)
    guard = setup_certified_guard(
        full_name=guard_name, home_zone_code=guard_zone,
        certification_expires_on=certification_expires_on,
        substitute_pool_optin=substitute_pool_optin)
    post = create_active_post(scenario["intersection"]["id"],
                              post_label=post_label, zone_code=zone_code,
                              required_shift=required_shift)
    assignment = create_assignment(post, guard["id"], start_date=start_date,
                                   end_date=end_date)
    scenario.update({
        "guard": get_success_data(api_client.get_guard(guard["id"], SUPERVISOR)),
        "post": get_success_data(api_client.get_guard_post(post["id"], ADMIN)),
        "assignment": assignment,
        "school": get_success_data(
            api_client.get_school(scenario["school"]["id"], ADMIN)),
    })
    return scenario


def add_second_post_and_guard(scenario: Dict[str, Any],
                              post_label: str = "Maple SE corner",
                              zone_code: str = "Z-NORTH",
                              required_shift: str = "AM",
                              guard_name: str = "Tomas Reyes",
                              guard_zone: str = "Z-NORTH",
                              start_date: str = "2026-09-08",
                              end_date: str = "2026-09-18",
                              substitute_pool_optin: Optional[bool] = None
                              ) -> Dict[str, Any]:
    """Add a second ACTIVE post on the same intersection, staffed by a second
    CERTIFIED guard. Returns {"post", "guard", "assignment"}."""
    guard = setup_certified_guard(full_name=guard_name,
                                  home_zone_code=guard_zone,
                                  substitute_pool_optin=substitute_pool_optin)
    post = create_active_post(scenario["intersection"]["id"],
                              post_label=post_label, zone_code=zone_code,
                              required_shift=required_shift)
    assignment = create_assignment(post, guard["id"], start_date=start_date,
                                   end_date=end_date)
    return {"post": post, "guard": guard, "assignment": assignment}


# ----------------------------------------------------------------------
# Tier 4: absence, substitute pool and dispatch
# ----------------------------------------------------------------------
def file_absence(assignment_id: str, absence_date: str = "2026-09-16",
                 reason: str = "ILLNESS", note: Optional[str] = "Flu.",
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """File an absence report against an assignment as the supervisor by default."""
    payload = create_absence_report_payload(assignment_id,
                                            absence_date=absence_date,
                                            reason=reason)
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.create_absence_report(
        payload, headers or SUPERVISOR))


def add_substitute_pool(zone_codes: Optional[List[Tuple[str, str]]] = None,
                        certification_expires_on: str = "2027-06-30"
                        ) -> List[Dict[str, Any]]:
    """Enroll opted-in CERTIFIED guards who hold no assignment, in the order given,
    so that `created_at` ordering is deterministic. Each tuple is (name, zone)."""
    pool = zone_codes if zone_codes is not None else [
        ("Sam Okafor", "Z-NORTH"), ("Nia Brandt", "Z-SOUTH")]
    return [setup_certified_guard(full_name=name, home_zone_code=zone,
                                 substitute_pool_optin=True,
                                 certification_expires_on=certification_expires_on)
            for name, zone in pool]


def setup_absence_ready_for_dispatch(
        absence_date: str = "2026-09-16",
        clock_at: Optional[str] = "2026-09-16T01:00:00Z",
        substitutes: Optional[List[Tuple[str, str]]] = None,
        substitute_expiries: Optional[List[str]] = None,
        required_shift: str = "AM",
        reason: str = "ILLNESS",
        scenario: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """A staffed post whose incumbent guard is opted out of the substitute pool,
    a set of opted-in substitutes, the clock moved to `clock_at`, and one filed
    absence report sitting in DISPATCH_PENDING.

    Returns the staffed-post scenario plus {"substitutes", "absence"}.
    """
    scenario = scenario or setup_staffed_post(required_shift=required_shift,
                                              substitute_pool_optin=False)
    names = substitutes if substitutes is not None else [
        ("Sam Okafor", "Z-NORTH"), ("Nia Brandt", "Z-SOUTH")]
    subs: List[Dict[str, Any]] = []
    for index, (name, zone) in enumerate(names):
        expires = "2027-06-30"
        if substitute_expiries is not None and index < len(substitute_expiries):
            expires = substitute_expiries[index]
        subs.append(setup_certified_guard(full_name=name, home_zone_code=zone,
                                          substitute_pool_optin=True,
                                          certification_expires_on=expires))
    if clock_at:
        advance_clock(clock_at)
    absence = file_absence(scenario["assignment"]["id"],
                           absence_date=absence_date, reason=reason)
    scenario = dict(scenario)
    scenario["substitutes"] = subs
    scenario["absence"] = absence
    return scenario


def dispatch(absence_id: str) -> Dict[str, Any]:
    """Offer the open duty day to the best-ranked eligible substitute."""
    return get_success_data(api_client.dispatch_absence_report(absence_id, SUPERVISOR))


def answer_offer(absence_id: str, guard_id: str, response: str) -> Dict[str, Any]:
    """Answer an open offer as the guard who currently holds it."""
    return get_success_data(api_client.respond_to_offer(
        absence_id, offer_response_payload(response),
        make_crossing_guard_headers(guard_id)))


def rescind(absence_id: str, reason: str = "Guard recovered.",
            headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.rescind_absence_report(
        absence_id, rescind_absence_payload(rescind_reason=reason),
        headers or SUPERVISOR))


# ----------------------------------------------------------------------
# Tier 4: walking routes
# ----------------------------------------------------------------------
def draft_route(school_id: str, segments: List[Dict[str, Any]],
                route_code: str = "RT-NORTH",
                route_name: str = "North corridor to Maple Grove",
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Draft a walking route as the school's own liaison unless told otherwise."""
    return get_success_data(api_client.create_walking_route(
        create_walking_route_payload(school_id, segments=segments,
                                     route_code=route_code,
                                     route_name=route_name),
        headers or make_school_liaison_headers(school_id)))


def publish_route(route_id: str, school_id: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.publish_walking_route(
        route_id, headers or make_school_liaison_headers(school_id)))


def setup_published_route(school_id: str,
                          segments: Optional[List[Dict[str, Any]]] = None,
                          route_code: str = "RT-NORTH") -> Dict[str, Any]:
    """Draft and publish a low-hazard route. One unmitigated NO_SIDEWALK segment
    of 133 feet scores 1.66, comfortably under the publication ceiling."""
    segments = segments if segments is not None else [
        route_segment(1, "NO_SIDEWALK", 133)]
    route = draft_route(school_id, segments, route_code=route_code)
    return publish_route(route["id"], school_id)


# ----------------------------------------------------------------------
# Tier 4: complaints, projects and grant awards
# ----------------------------------------------------------------------
def file_complaint(intersection_id: str, headers: Optional[Dict[str, str]] = None,
                   **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_complaint(
        intersection_id, create_complaint_payload(**overrides),
        headers or REPORTER))


def setup_triaged_complaint(intersection_id: str, **overrides) -> Dict[str, Any]:
    """A complaint referred to engineering, so it is eligible to be cited."""
    complaint = file_complaint(intersection_id, **overrides)
    return get_success_data(api_client.triage_complaint(
        complaint["id"],
        triage_complaint_payload("REFER_TO_ENGINEERING",
                                 triage_note="Refer for countermeasure design."),
        ENGINEER))


def propose_project(grant_program_id: str, intersection_id: str,
                    requested_cost_cents: int = 4_000_000,
                    students_benefited: int = 320,
                    source_complaint_id: Optional[str] = None,
                    project_type: str = "RRFB",
                    scope_summary: str = "Install a rapid flashing beacon."
                    ) -> Dict[str, Any]:
    payload = create_project_payload(
        grant_program_id, intersection_id,
        requested_cost_cents=requested_cost_cents,
        students_benefited=students_benefited,
        project_type=project_type, scope_summary=scope_summary)
    if source_complaint_id is not None:
        payload["source_complaint_id"] = source_complaint_id
    return get_success_data(
        api_client.create_infrastructure_project(payload, ENGINEER))


def score_project(project_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.score_project(project_id, ENGINEER))


def setup_scored_project(grant_program_id: str, intersection_id: str,
                         **project_kwargs) -> Dict[str, Any]:
    """Propose then score a project so it enters the program's ranking pool."""
    project = propose_project(grant_program_id, intersection_id, **project_kwargs)
    return score_project(project["id"])


def fund(project_id: str, program: Dict[str, Any],
         award_note: Optional[str] = None) -> Dict[str, Any]:
    """Award the pool's money to a project, declaring the program's version."""
    payload = fund_project_payload(program["version"])
    if award_note is not None:
        payload["award_note"] = award_note
    return get_success_data(api_client.fund_project(project_id, payload, ADMIN))


def withdraw(project_id: str, program: Dict[str, Any],
             reason: str = "Bid came in over the award ceiling.") -> Dict[str, Any]:
    return get_success_data(api_client.withdraw_funding(
        project_id, withdraw_funding_payload(program["version"],
                                             withdrawal_reason=reason),
        ADMIN))


def read_program(program_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_grant_program(program_id, ADMIN))


def setup_grant_competition(total_cents: int,
                            requests: List[Tuple[int, int]],
                            scenario: Optional[Dict[str, Any]] = None
                            ) -> Dict[str, Any]:
    """A finalized WARRANTED intersection, a grant program and one SCORED project
    per (requested_cost_cents, students_benefited) pair, created in order so that
    `created_at` ordering is deterministic.

    Returns {"school", "intersection", "study", "program", "projects"}.
    """
    scenario = dict(scenario) if scenario else setup_warranted_intersection()
    program = create_grant_program(total_cents=total_cents)
    projects = [
        setup_scored_project(program["id"], scenario["intersection"]["id"],
                            requested_cost_cents=cost,
                            students_benefited=students)
        for cost, students in requests
    ]
    scenario["program"] = read_program(program["id"])
    scenario["projects"] = projects
    return scenario


# ----------------------------------------------------------------------
# Mode-share surveys
# ----------------------------------------------------------------------
def append_survey(school_id: str, headers: Optional[Dict[str, str]] = None,
                  **overrides) -> Dict[str, Any]:
    """Append a term travel-tally survey as the school's own liaison by default."""
    return get_success_data(api_client.create_mode_share_survey(
        school_id, create_mode_share_survey_payload(**overrides),
        headers or make_school_liaison_headers(school_id)))


# ----------------------------------------------------------------------
# Read-back helpers
# ----------------------------------------------------------------------
def read_school(school_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_school(school_id, ADMIN))


def read_intersection(intersection_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_intersection(intersection_id, ADMIN))


def read_study(study_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_warrant_study(study_id, ENGINEER))


def read_guard(guard_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_guard(guard_id, SUPERVISOR))


def read_post(post_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_guard_post(post_id, ADMIN))


def read_assignment(assignment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_post_assignment(assignment_id, SUPERVISOR))


def read_absence(absence_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_absence_report(absence_id, SUPERVISOR))


def read_route(route_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_walking_route(route_id, ADMIN))


def read_complaint(complaint_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_complaint(complaint_id, ENGINEER))


def read_project(project_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_infrastructure_project(project_id, ENGINEER))
