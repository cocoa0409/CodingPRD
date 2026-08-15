"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: every non-NewsDirector role is entity-backed by
StaffMember, so a workspace context carries per-instance headers built from
the real staff ids via the make_* builders; ownership-gated calls never fall
back to the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_analytics_report_payload,
    create_assignment_payload,
    create_breaking_event_payload,
    create_correction_payload,
    create_pitch_payload,
    create_review_payload,
    create_slot_payload,
    create_staff_payload,
    schedule_payload,
)
from .test_users import (
    TEST_USERS,
    make_analytics_producer_headers,
    make_assignment_editor_headers,
    make_copy_editor_headers,
    make_fact_checker_headers,
    make_legal_reviewer_headers,
    make_managing_editor_headers,
    make_news_director_headers,
    make_photographer_headers,
    make_reporter_headers,
)

ND = TEST_USERS["news_director_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the logical clock (NewsDirector-only test-driving endpoint)."""
    return get_success_data(api_client.set_clock(to_iso8601, ND))


def make_staff(full_name, role_capability, home_desk="METRO",
               hourly_rate_cents=6000, max_concurrent_assignments=None):
    """Create a staff member (born ACTIVE, count 0, version 1)."""
    payload = create_staff_payload(
        full_name=full_name, role_capability=role_capability,
        home_desk=home_desk, hourly_rate_cents=hourly_rate_cents,
        max_concurrent_assignments=max_concurrent_assignments,
    )
    return get_success_data(api_client.create_staff(payload, ND))


def patch_staff(staff_id, **fields):
    """NewsDirector patch: employment_status / max_concurrent_assignments /
    hourly_rate_cents."""
    return get_success_data(api_client.patch_staff(staff_id, fields, ND))


def create_slot(headers, channel="PRINT", window_start="2026-08-05T18:00:00Z",
                window_end="2026-08-05T19:00:00Z", capacity=1):
    """Open a publication slot (born ACTIVE, reserved_count 0)."""
    payload = create_slot_payload(channel=channel, window_start=window_start,
                                  window_end=window_end, capacity=capacity)
    return get_success_data(api_client.create_slot(payload, headers))


def declare_event(title="Breaking", priority_band=2,
                  window_start="2026-08-01T09:00:00Z",
                  window_end="2026-08-01T12:00:00Z", call_in_pool_size=0):
    """Declare a breaking-news event (born DECLARED)."""
    payload = create_breaking_event_payload(
        title=title, priority_band=priority_band, window_start=window_start,
        window_end=window_end, call_in_pool_size=call_in_pool_size,
    )
    return get_success_data(api_client.create_breaking_event(payload, ND))


def story_version(story_id):
    """Read the story's current version (fresh OCC token)."""
    return get_success_data(api_client.get_story(story_id, ND))["version"]


def file_review(story_id, review_type, verdict, reviewer_headers,
                expected_story_version=None, notes=None):
    """File a review verdict, threading a fresh OCC token when not given."""
    if expected_story_version is None:
        expected_story_version = story_version(story_id)
    payload = create_review_payload(review_type, verdict,
                                    expected_story_version, notes=notes)
    return api_client.create_story_review(story_id, payload, reviewer_headers)


# ---------------------------------------------------------------------------
# Tier 2: the newsroom roster
# ---------------------------------------------------------------------------

_ROLE_BUILDERS = {
    "reporter": make_reporter_headers,
    "photographer": make_photographer_headers,
    "copy_editor": make_copy_editor_headers,
    "fact_checker": make_fact_checker_headers,
    "legal_reviewer": make_legal_reviewer_headers,
    "desk": make_assignment_editor_headers,
    "managing_editor": make_managing_editor_headers,
    "analyst": make_analytics_producer_headers,
}

_ROLE_CAPABILITIES = {
    "reporter": "REPORTER",
    "photographer": "PHOTOGRAPHER",
    "copy_editor": "COPY_EDITOR",
    "fact_checker": "FACT_CHECKER",
    "legal_reviewer": "LEGAL_REVIEWER",
    "desk": "DESK_EDITOR",
    "managing_editor": "MANAGING_EDITOR",
    "analyst": "ANALYST",
}

# Header builder selected by the staff member's role_capability — the ctx key
# is an arbitrary label ("reporter_b", "managing_editor_2", ...) and must NOT
# drive role selection. PRD §2.1: every entity-backed header role resolves
# X-User-ID to a StaffMember; the capability governs assignment matching.
_CAPABILITY_BUILDERS = {
    "REPORTER": make_reporter_headers,
    "PHOTOGRAPHER": make_photographer_headers,
    "COPY_EDITOR": make_copy_editor_headers,
    "FACT_CHECKER": make_fact_checker_headers,
    "LEGAL_REVIEWER": make_legal_reviewer_headers,
    "DESK_EDITOR": make_assignment_editor_headers,
    "MANAGING_EDITOR": make_managing_editor_headers,
    "NEWS_DIRECTOR": make_news_director_headers,
    "ANALYST": make_analytics_producer_headers,
}


def setup_newsroom(copy_editor=False, fact_checker=False, legal_reviewer=False,
                   managing_editor=False, analyst=False, photographer=False,
                   reporter_rate=6000, reporter_max=None,
                   reporter_desk="METRO"):
    """Create the desk editor + reporter core plus any requested specialists.

    Returns a dict with each staff body under its key ("desk", "reporter",
    "copy_editor", ...) and ready-to-use per-instance headers under
    "<key>_headers".
    """
    ctx = {}
    desk = make_staff("Desk Editor", "DESK_EDITOR", "METRO", 6000)
    ctx["desk"] = desk
    ctx["desk_headers"] = make_assignment_editor_headers(desk["id"])
    rep = make_staff("Staff Reporter", "REPORTER", reporter_desk,
                     reporter_rate, reporter_max)
    ctx["reporter"] = rep
    ctx["reporter_headers"] = make_reporter_headers(rep["id"])

    requested = {
        "photographer": ("Staff Photographer", 5000, "METRO"),
        "copy_editor": ("Copy Editor", 6000, "METRO"),
        "fact_checker": ("Fact Checker", 6000, "METRO"),
        "legal_reviewer": ("Legal Reviewer", 6000, "METRO"),
        "managing_editor": ("Managing Editor", 8000, "METRO"),
        "analyst": ("Audience Analyst", 6000, "METRO"),
    }
    flags = {
        "photographer": photographer,
        "copy_editor": copy_editor,
        "fact_checker": fact_checker,
        "legal_reviewer": legal_reviewer,
        "managing_editor": managing_editor,
        "analyst": analyst,
    }
    for key, wanted in flags.items():
        if not wanted:
            continue
        name, rate, desk_aff = requested[key]
        member = make_staff(name, _ROLE_CAPABILITIES[key], desk_aff, rate)
        ctx[key] = member
        ctx[f"{key}_headers"] = _ROLE_BUILDERS[key](member["id"])
    return ctx


def add_staff_to(ctx, key, role_capability, full_name=None, home_desk="METRO",
                 hourly_rate_cents=6000, max_concurrent_assignments=None):
    """Grow an existing newsroom context with one more staff member."""
    member = make_staff(full_name or f"Extra {role_capability}",
                        role_capability, home_desk, hourly_rate_cents,
                        max_concurrent_assignments)
    ctx[key] = member
    ctx[f"{key}_headers"] = _CAPABILITY_BUILDERS[role_capability](member["id"])
    return member


# ---------------------------------------------------------------------------
# Tier 3: pitch intake and greenlight
# ---------------------------------------------------------------------------

def submit_pitch(ctx, title="Test Pitch", summary="Angle summary",
                 desk="METRO", urgency="STANDARD",
                 deadline_at="2026-08-03T00:00:00Z", author_headers=None):
    """Submit a pitch as the given author (default: the reporter)."""
    headers = author_headers or ctx["reporter_headers"]
    payload = create_pitch_payload(title=title, summary=summary, desk=desk,
                                   deadline_at=deadline_at, urgency=urgency)
    return get_success_data(api_client.create_pitch(payload, headers))


def greenlight(ctx, pitch_id, story_type="PRINT"):
    """SUBMITTED -> DESK_REVIEW -> GREENLIT. Returns the updated pitch."""
    get_success_data(api_client.start_pitch_review(pitch_id, ctx["desk_headers"]))
    return get_success_data(api_client.greenlight_pitch(
        pitch_id, {"story_type": story_type}, ctx["desk_headers"]))


def create_greenlit_story(ctx, story_type="PRINT", **pitch_kwargs):
    """Pitch -> start-review -> greenlight. Returns (pitch, story_id)."""
    pitch = submit_pitch(ctx, **pitch_kwargs)
    pitch = greenlight(ctx, pitch["id"], story_type=story_type)
    return pitch, pitch["greenlit_story_id"]


# ---------------------------------------------------------------------------
# Tier 3b: assignments
# ---------------------------------------------------------------------------

def propose_assignment(ctx, story_id, staff_id, assignment_role="REPORTER",
                       start_at="2026-08-01T08:00:00Z",
                       end_at="2026-08-01T09:00:00Z",
                       planned_effort_minutes=60):
    """Propose an assignment as the desk editor. Returns the Assignment."""
    payload = create_assignment_payload(
        story_id, staff_id, assignment_role=assignment_role,
        start_at=start_at, end_at=end_at,
        planned_effort_minutes=planned_effort_minutes,
    )
    return get_success_data(
        api_client.create_assignment(payload, ctx["desk_headers"]))


def accept_assignment_as(assignee_headers, assignment_id):
    return get_success_data(
        api_client.accept_assignment(assignment_id, assignee_headers))


def propose_and_accept(ctx, story_id, staff_key="reporter", **kwargs):
    """Propose then accept as the assignee. Returns the ACCEPTED assignment."""
    staff_id = ctx[staff_key]["id"]
    asg = propose_assignment(ctx, story_id, staff_id, **kwargs)
    return accept_assignment_as(ctx[f"{staff_key}_headers"], asg["id"])


# ---------------------------------------------------------------------------
# Tier 4: editorial pipeline drivers
# ---------------------------------------------------------------------------

def drive_story_to_cleared(ctx, story_id, author_headers=None,
                           word_count=None, embargo_until=None,
                           assignment_window=("2026-08-01T08:00:00Z",
                                              "2026-08-01T09:00:00Z"),
                           planned_effort_minutes=60, crew=True):
    """Walk a DRAFT story to CLEARED: accepted reporter assignment (unless
    crew=False), optional author PATCH, submit-edit, complete-edit,
    FACT_CHECK PASS, LEGAL PASS. Returns the CLEARED story body."""
    author = author_headers or ctx["reporter_headers"]
    if crew:
        propose_and_accept(ctx, story_id, "reporter",
                           start_at=assignment_window[0],
                           end_at=assignment_window[1],
                           planned_effort_minutes=planned_effort_minutes)
    patch = {}
    if word_count is not None:
        patch["word_count"] = word_count
    if embargo_until is not None:
        patch["embargo_until"] = embargo_until
    if patch:
        get_success_data(api_client.patch_story(story_id, patch, author))
    get_success_data(api_client.submit_story_edit(story_id, author))
    get_success_data(
        api_client.complete_story_edit(story_id, ctx["copy_editor_headers"]))
    get_success_data(file_review(story_id, "FACT_CHECK", "PASS",
                                 ctx["fact_checker_headers"]))
    get_success_data(file_review(story_id, "LEGAL", "PASS",
                                 ctx["legal_reviewer_headers"]))
    return get_success_data(api_client.get_story(story_id, ND))


def setup_cleared_story(story_type="PRINT", **kwargs):
    """Full roster + greenlit story driven to CLEARED.

    Returns (ctx, story). ctx carries desk/reporter/copy_editor/fact_checker/
    legal_reviewer and their headers; story is the CLEARED story body.
    """
    ctx = setup_newsroom(copy_editor=True, fact_checker=True,
                         legal_reviewer=True)
    pitch_kwargs = {k: kwargs.pop(k) for k in
                    ("desk", "urgency", "deadline_at", "title", "summary")
                    if k in kwargs}
    _pitch, story_id = create_greenlit_story(ctx, story_type=story_type,
                                             **pitch_kwargs)
    story = drive_story_to_cleared(ctx, story_id, **kwargs)
    return ctx, story


def schedule(ctx, story_id, slot_id, expected_story_version=None):
    """CLEARED -> SCHEDULED with a fresh OCC token when not given."""
    if expected_story_version is None:
        expected_story_version = story_version(story_id)
    return get_success_data(api_client.schedule_story(
        story_id, schedule_payload(slot_id, expected_story_version),
        ctx["desk_headers"]))


def setup_scheduled_story(slot_channel="PRINT",
                          slot_window=("2026-08-05T18:00:00Z",
                                       "2026-08-05T19:00:00Z"),
                          slot_capacity=1, story_type="PRINT", **kwargs):
    """CLEARED story scheduled into a fresh slot.

    Returns (ctx, story, slot).
    """
    ctx, story = setup_cleared_story(story_type=story_type, **kwargs)
    slot = create_slot(ctx["desk_headers"], channel=slot_channel,
                       window_start=slot_window[0], window_end=slot_window[1],
                       capacity=slot_capacity)
    story = schedule(ctx, story["id"], slot["id"])
    return ctx, story, slot


def publish_scheduled(story_id, publish_at="2026-08-01T06:30:00Z"):
    """Advance the logical clock and run the publication scheduler."""
    set_clock(publish_at)
    return get_success_data(api_client.run_publication_scheduler(ND))


def setup_published_story(with_managing_editor=False, with_analyst=False,
                          slot_window=("2026-08-01T06:00:00Z",
                                       "2026-08-01T07:00:00Z"),
                          slot_capacity=1, slot_channel="PRINT",
                          assignment_window=("2026-08-01T01:00:00Z",
                                             "2026-08-01T03:00:00Z"),
                          publish_at="2026-08-01T06:30:00Z", **kwargs):
    """Full pipeline to PUBLISHED: cleared story, scheduled into a slot whose
    window has opened, then the ops checkpoint publishes it.

    Returns (ctx, story, slot). ctx includes managing_editor / analyst when
    requested.
    """
    ctx = setup_newsroom(copy_editor=True, fact_checker=True,
                         legal_reviewer=True,
                         managing_editor=with_managing_editor,
                         analyst=with_analyst)
    pitch_kwargs = {k: kwargs.pop(k) for k in
                    ("desk", "urgency", "deadline_at", "title", "summary")
                    if k in kwargs}
    story_type = kwargs.pop("story_type", "PRINT")
    _pitch, story_id = create_greenlit_story(ctx, story_type=story_type,
                                             **pitch_kwargs)
    drive_story_to_cleared(ctx, story_id,
                           assignment_window=assignment_window, **kwargs)
    slot = create_slot(ctx["desk_headers"], channel=slot_channel,
                       window_start=slot_window[0], window_end=slot_window[1],
                       capacity=slot_capacity)
    schedule(ctx, story_id, slot["id"])
    publish_scheduled(story_id, publish_at=publish_at)
    story = get_success_data(api_client.get_story(story_id, ND))
    return ctx, story, slot


# ---------------------------------------------------------------------------
# Tier 5: corrections and analytics on a published story
# ---------------------------------------------------------------------------

def propose_correction(proposer_headers, story_id, severity="MINOR",
                       correction_text="Correction text"):
    payload = create_correction_payload(severity=severity,
                                        correction_text=correction_text)
    return get_success_data(
        api_client.create_story_correction(story_id, payload,
                                           proposer_headers))


def ingest_analytics(ctx, story_id, variant="SETTLED",
                     window_start="2026-08-01T07:00:00Z",
                     window_end="2026-08-02T07:00:00Z", views=100,
                     engagement_minutes=50):
    payload = create_analytics_report_payload(
        variant=variant, window_start=window_start, window_end=window_end,
        views=views, engagement_minutes=engagement_minutes)
    return get_success_data(api_client.create_story_analytics_report(
        story_id, payload, ctx["analyst_headers"]))


# ---------------------------------------------------------------------------
# Tier 5b: breaking news
# ---------------------------------------------------------------------------

def activate_event(event_id):
    return get_success_data(api_client.activate_breaking_event(event_id, ND))


def declare_and_activate_event(priority_band=2,
                               window_start="2026-08-01T09:00:00Z",
                               window_end="2026-08-01T12:00:00Z",
                               call_in_pool_size=0, title="Breaking"):
    """Declare + activate. Returns the ACTIVE event."""
    event = declare_event(title=title, priority_band=priority_band,
                          window_start=window_start, window_end=window_end,
                          call_in_pool_size=call_in_pool_size)
    return activate_event(event["id"])


def event_call_ins(event_id):
    """All call-ins paged for an event, in creation order."""
    return get_success_data(api_client.get_event_call_ins(event_id, ND))
