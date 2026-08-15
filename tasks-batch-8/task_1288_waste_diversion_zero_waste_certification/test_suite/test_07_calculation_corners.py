"""Calculation corners: severity boundaries, goal evaluation, event counting,
and program standing (PRD §3.5, §3.6)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_site, create_period, create_goal, create_event,
    set_clock, TEST_USERS,
)

OFFICER = TEST_USERS["officer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_contamination_severity_boundaries(api):
    """PRD §3.5: "The event's severity is computed from the percentage with
    floors inclusive at the boundary: below 5 the event is MINOR; at least 5
    but below 10 it is MAJOR, so exactly 5.0 is MAJOR; at least 10 it is
    CRITICAL, so exactly 10.0 is CRITICAL."

    Design: Corner/calculations/contamination_severity_boundaries
    """
    site = create_site("Site SB")
    minor = create_event(site["id"], event_date="2026-08-05",
                         material_stream="MIXED_RECYCLABLES", contamination_pct=4.9)
    major = create_event(site["id"], event_date="2026-08-05",
                         material_stream="MIXED_RECYCLABLES", contamination_pct=5.0)
    critical = create_event(site["id"], event_date="2026-08-05",
                            material_stream="MIXED_RECYCLABLES", contamination_pct=10.0)
    assert minor["severity"] == "MINOR"
    assert major["severity"] == "MAJOR"
    assert critical["severity"] == "CRITICAL"


def test_goal_contamination_events_at_target_achieved(api):
    """PRD §3.6: "A `CONTAMINATION_EVENTS` goal is achieved when the frozen
    `contamination_event_count` is less than or equal to its `target_value`."

    Design: Corner/calculations/goal_contamination_events_at_target_achieved
    """
    set_clock()
    site = create_site("Site GE")
    period = create_period(site["id"])
    goal = create_goal(site["id"], metric="CONTAMINATION_EVENTS", target_value=1)
    create_event(site["id"], event_date="2026-08-05",
                 material_stream="MIXED_RECYCLABLES", contamination_pct=3)
    get_success_data(api.close_period(period["id"], OFFICER))
    g = get_success_data(api.get_goal(goal["id"], OFFICER))
    assert g["status"] == "ACHIEVED"
    p = get_success_data(api.get_period(period["id"], OFFICER))
    assert p["contamination_event_count"] == 1


def test_dismissed_event_excluded_from_count(api):
    """PRD §3.5: "DISMISSED and VERIFIED_CLOSED events are excluded from the
    derivation, and dismissed events also drop out of every period's
    contamination_event_count."

    Design: Corner/calculations/dismissed_event_excluded_from_count
    """
    set_clock()
    site = create_site("Site DX")
    period = create_period(site["id"])
    goal = create_goal(site["id"], metric="CONTAMINATION_EVENTS", target_value=0)
    ev = create_event(site["id"], event_date="2026-08-05",
                      material_stream="MIXED_RECYCLABLES", contamination_pct=3)
    get_success_data(api.dismiss_event(ev["id"], {"reason": "duplicate observation"}, AUDITOR))
    get_success_data(api.close_period(period["id"], OFFICER))
    p = get_success_data(api.get_period(period["id"], OFFICER))
    assert p["contamination_event_count"] == 0
    g = get_success_data(api.get_goal(goal["id"], OFFICER))
    assert g["status"] == "ACHIEVED"


def test_standing_watch_at_two_open_events(api):
    """PRD §3.5: "Standing is computed over the site's non-terminal events,
    meaning those in OPEN, TRAINING_ASSIGNED, or TRAINING_COMPLETED ... If
    any non-terminal event is CRITICAL, the site is on PROBATION. Otherwise,
    if at least two non-terminal events exist, the site is on WATCH. Otherwise
    the site is in GOOD_STANDING."

    Design: Corner/calculations/standing_watch_at_two_open_events
    """
    site = create_site("Site SW")
    create_event(site["id"], event_date="2026-08-05",
                 material_stream="CARDBOARD", contamination_pct=3)
    s1 = get_success_data(api.get_site(site["id"], OFFICER))
    assert s1["program_standing"] == "GOOD_STANDING"
    create_event(site["id"], event_date="2026-08-06",
                 material_stream="MIXED_RECYCLABLES", contamination_pct=6)
    s2 = get_success_data(api.get_site(site["id"], OFFICER))
    assert s2["program_standing"] == "WATCH"
