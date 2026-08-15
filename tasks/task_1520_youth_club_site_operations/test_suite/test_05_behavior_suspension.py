"""Behavior incidents, discipline points, suspensions, and appeals."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    adjudicate_incident,
    create_active_member,
    create_credentialed_staff,
    director_headers,
    get_member,
    make_site_director_headers,
    open_club_day,
    report_incident,
    set_logical_clock,
    setup_site_with_director,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _get_incident(api, member_id, incident_id):
    data, _ = validate_paginated(api.list_member_incidents(member_id, ADMIN))
    for inc in data:
        if inc["id"] == incident_id:
            return inc
    raise AssertionError(f"incident {incident_id} not found for member {member_id}")


def test_incident_adjudicate_twice_returns_not_reported(api):
    """PRD 3.8: "Adjudication belongs to the `SiteDirector` and requires the
    incident `REPORTED` (`ERR_INCIDENT_NOT_REPORTED`, 409)".

    Design: Corner/state_machines/c_incident_adjudicate_twice_returns_not_reported
    """
    site, director = setup_site_with_director(clock="2026-08-03T10:00:00Z")
    member = create_active_member(site["id"], director["id"], legal_name="Kid A")
    incident = report_incident(member["id"], director["id"], "2026-08-03",
                               "LEVEL_1")
    adjudicate_incident(incident["id"], director["id"], "SUSTAINED")
    res = api.adjudicate_incident(incident["id"], {"outcome": "DISMISS"},
                                  director_headers(director))
    validate_error(res, ApiErrorId.ERR_INCIDENT_NOT_REPORTED, expected_status=409)
    inc = _get_incident(api, member["id"], incident["id"])
    assert inc["adjudication_status"] == "ADJUDICATED"
    assert get_member(member["id"])["behavior_points"] == 1


def test_appeal_without_active_suspension_returns_not_appealable(api):
    """PRD 3.8: "appealing anything whose `suspension_status` is not `ACTIVE`
    is rejected with `ERR_INCIDENT_NOT_APPEALABLE`".

    Design: Corner/state_machines/c_appeal_without_active_suspension_returns_not_appealable
    """
    site, director = setup_site_with_director(clock="2026-08-03T10:00:00Z")
    member = create_active_member(site["id"], director["id"], legal_name="Kid A")
    incident = report_incident(member["id"], director["id"], "2026-08-03",
                               "LEVEL_1")
    adjudicate_incident(incident["id"], director["id"], "SUSTAINED")
    res = api.appeal_incident(incident["id"], director_headers(director))
    validate_error(res, ApiErrorId.ERR_INCIDENT_NOT_APPEALABLE,
                   expected_status=409)
    inc = _get_incident(api, member["id"], incident["id"])
    assert inc["suspension_status"] == "NONE"


def test_resolve_appeal_without_appeal_returns_not_pending(api):
    """PRD 3.8: "Resolution is a `SiteDirector` action requiring the suspension
    `APPEALED` (`ERR_APPEAL_NOT_PENDING`) and a resolver whose `X-User-ID`
    differs from the recorded `adjudicated_by_user_id`
    (`ERR_SEGREGATION_OF_DUTIES`, 403)."

    Design: Corner/state_machines/c_resolve_appeal_without_appeal_returns_not_pending
    """
    site, director = setup_site_with_director(clock="2026-08-03T10:00:00Z")
    director2 = create_credentialed_staff(site["id"], "Dir Two", "DIRECTOR")
    member = create_active_member(site["id"], director["id"], legal_name="Kid A")
    incident = report_incident(member["id"], director["id"], "2026-08-03",
                               "LEVEL_2")
    adjudicate_incident(incident["id"], director["id"], "SUSTAINED",
                        suspension_days=2, suspension_start_date="2026-08-03")
    # suspension is ACTIVE but was never appealed; a different director resolves
    res = api.resolve_appeal(incident["id"], {"decision": "UPHELD"},
                             make_site_director_headers(director2["id"]))
    validate_error(res, ApiErrorId.ERR_APPEAL_NOT_PENDING, expected_status=409)
    inc = _get_incident(api, member["id"], incident["id"])
    assert inc["suspension_status"] == "ACTIVE"
    assert get_member(member["id"])["status"] == "SUSPENDED"


def test_points_rolling_window_excludes_older_than_90_days(api):
    """PRD 3.8: "A member's `behavior_points` are the summed `points` of the
    member's incidents that are `ADJUDICATED`, whose suspension has not been
    `RESCINDED`, and whose `incident_date` falls inside the rolling ninety-day
    window — from ninety days before logical today through today, both ends
    inclusive."

    Design: Corner/calculations/c_points_rolling_window_excludes_older_than_90_days
    """
    site, director = setup_site_with_director(clock="2026-08-01T09:00:00Z")
    member = create_active_member(site["id"], director["id"], legal_name="Kid A")
    set_logical_clock("2026-08-13T09:00:00Z")
    # at today 2026-08-13 the window is [2026-05-15, 2026-08-13]
    inc_in = report_incident(member["id"], director["id"], "2026-05-15",
                             "LEVEL_1")
    inc_out = report_incident(member["id"], director["id"], "2026-05-14",
                              "LEVEL_2")
    adjudicate_incident(inc_in["id"], director["id"], "SUSTAINED")
    adjudicate_incident(inc_out["id"], director["id"], "SUSTAINED")
    member = get_member(member["id"])
    assert member["behavior_points"] == 1, (
        "LEVEL_1 at exactly 90 days back counts; LEVEL_2 at 91 days is excluded"
    )
    assert member["discipline_watch"] is False


def test_suspension_mandatory_once_watch_threshold_reached(api):
    """PRD 3.8: "When the total reaches ten points — exactly ten is enough —
    the member's `discipline_watch` turns true." and "once the watch is on,
    imposing a suspension is mandatory, and adjudicating without a positive
    `suspension_days` is rejected with `ERR_SUSPENSION_MANDATORY` (422)."

    Design: Corner/calculations/c_suspension_mandatory_once_watch_threshold_reached
    """
    site, director = setup_site_with_director(clock="2026-08-03T10:00:00Z")
    member = create_active_member(site["id"], director["id"], legal_name="Kid A")
    i1 = report_incident(member["id"], director["id"], "2026-08-03", "LEVEL_3")
    i2 = report_incident(member["id"], director["id"], "2026-08-03", "LEVEL_3")
    i3 = report_incident(member["id"], director["id"], "2026-08-03", "LEVEL_1")
    # legal while the watch is still off (each adjudication precedes the flip)
    adjudicate_incident(i1["id"], director["id"], "SUSTAINED")
    adjudicate_incident(i2["id"], director["id"], "SUSTAINED")
    member = get_member(member["id"])
    assert member["behavior_points"] == 16
    assert member["discipline_watch"] is True

    res = api.adjudicate_incident(i3["id"], {"outcome": "SUSTAINED"},
                                  director_headers(director))
    validate_error(res, ApiErrorId.ERR_SUSPENSION_MANDATORY, expected_status=422)
    inc = _get_incident(api, member["id"], i3["id"])
    assert inc["adjudication_status"] == "REPORTED"

    resolved = adjudicate_incident(i3["id"], director["id"], "SUSTAINED",
                                   suspension_days=1,
                                   suspension_start_date="2026-08-03")
    assert resolved["suspension_status"] == "ACTIVE"
    assert get_member(member["id"])["status"] == "SUSPENDED"


def test_appeal_resolve_segregation_of_duties(api):
    """PRD 3.8: "Resolution is a `SiteDirector` action requiring the suspension
    `APPEALED` (`ERR_APPEAL_NOT_PENDING`) and a resolver whose `X-User-ID`
    differs from the recorded `adjudicated_by_user_id`
    (`ERR_SEGREGATION_OF_DUTIES`, 403). A `decision` of `UPHELD` moves the
    suspension to `RESCINDED`: the incident's points stop counting toward
    `behavior_points` (recomputing the watch), and the member returns from
    `SUSPENDED` to `ACTIVE` provided no other incident still holds an `ACTIVE`
    suspension for them".

    Design: Corner/rbac/c_appeal_resolve_segregation_of_duties
    """
    site, director = setup_site_with_director(clock="2026-08-03T10:00:00Z")
    director2 = create_credentialed_staff(site["id"], "Dir Two", "DIRECTOR")
    member = create_active_member(site["id"], director["id"], legal_name="Kid A")
    incident = report_incident(member["id"], director["id"], "2026-08-03",
                               "LEVEL_2")
    adjudicate_incident(incident["id"], director["id"], "SUSTAINED",
                        suspension_days=2, suspension_start_date="2026-08-03")
    validate_success(api.appeal_incident(incident["id"],
                                         director_headers(director)), 200)

    # the adjudicator may not resolve their own appeal
    res = api.resolve_appeal(incident["id"], {"decision": "UPHELD"},
                             director_headers(director))
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
    inc = _get_incident(api, member["id"], incident["id"])
    assert inc["suspension_status"] == "APPEALED"

    resolved = validate_success(
        api.resolve_appeal(incident["id"], {"decision": "UPHELD"},
                           make_site_director_headers(director2["id"])),
        200,
    )
    assert resolved["suspension_status"] == "RESCINDED"
    member = get_member(member["id"])
    assert member["status"] == "ACTIVE"
    assert member["behavior_points"] == 0, "the rescinded incident un-counts"


def _setup_appeal_cycle(api):
    """LEVEL_3 incident sustained with a 2-day suspension starting 2026-08-03;
    two directors (d1 adjudicates, d2 resolves). Returns (site, d1, d2, member,
    incident)."""
    site, director = setup_site_with_director(clock="2026-08-01T09:00:00Z")
    director2 = create_credentialed_staff(site["id"], "Dir Two", "DIRECTOR")
    member = create_active_member(site["id"], director["id"], legal_name="Kid X",
                                  date_of_birth="2011-01-01", grade=8)
    set_logical_clock("2026-08-03T10:00:00Z")
    incident = report_incident(member["id"], director["id"], "2026-08-03",
                               "LEVEL_3")
    return site, director, director2, member, incident


def test_incident_appeal_cycle_adjudicate_and_appeal(api):
    """PRD 3.8: "if the start date is today or earlier, the suspension becomes
    `ACTIVE` immediately and the member flips from `ACTIVE` to `SUSPENDED` on
    the spot" and "The suspension moves to `APPEALED`, and the member remains
    `SUSPENDED` while the appeal pends."

    Design: Difficulty/non_linear_state_machine/incident_parallel_dimensions_with_appeal_cycle
    """
    site, director, director2, member, incident = _setup_appeal_cycle(api)
    adjudicated = adjudicate_incident(incident["id"], director["id"], "SUSTAINED",
                                      suspension_days=2,
                                      suspension_start_date="2026-08-03")
    assert adjudicated["adjudication_status"] == "ADJUDICATED"
    assert adjudicated["suspension_status"] == "ACTIVE"
    assert adjudicated["adjudicated_by_user_id"] == director["id"]
    assert get_member(member["id"])["status"] == "SUSPENDED"

    appealed = validate_success(
        api.appeal_incident(incident["id"], director_headers(director)), 200
    )
    assert appealed["suspension_status"] == "APPEALED"
    member = get_member(member["id"])
    assert member["status"] == "SUSPENDED", "member stays suspended during appeal"
    assert member["behavior_points"] == 8, "LEVEL_3 contributes 8 points"


def test_incident_appeal_cycle_denied_then_served(api):
    """PRD 3.8: "A `decision` of `DENIED` returns the suspension to `ACTIVE`
    and the member stays suspended." PRD 3.4: "every suspension already
    `ACTIVE` whose full window — from `suspension_start_date` forward
    `suspension_days` calendar days, end-exclusive — has elapsed by the new
    date becomes `SERVED`, returning the member from `SUSPENDED` to `ACTIVE`
    provided no other incident still holds an `ACTIVE` suspension for that
    member."

    Design: Difficulty/non_linear_state_machine/incident_parallel_dimensions_with_appeal_cycle
    """
    site, director, director2, member, incident = _setup_appeal_cycle(api)
    adjudicate_incident(incident["id"], director["id"], "SUSTAINED",
                        suspension_days=2, suspension_start_date="2026-08-03")
    validate_success(api.appeal_incident(incident["id"],
                                         director_headers(director)), 200)
    resolved = validate_success(
        api.resolve_appeal(incident["id"], {"decision": "DENIED"},
                           make_site_director_headers(director2["id"])),
        200,
    )
    assert resolved["suspension_status"] == "ACTIVE", (
        "the cycle closes APPEALED -> ACTIVE on a denied appeal"
    )
    assert get_member(member["id"])["status"] == "SUSPENDED"

    # window [2026-08-03, 2026-08-05) has elapsed by 2026-08-06; the open sweep serves it
    open_club_day(site["id"], director["id"], "2026-08-06")
    inc = _get_incident(api, member["id"], incident["id"])
    assert inc["suspension_status"] == "SERVED"
    member = get_member(member["id"])
    assert member["status"] == "ACTIVE"
    assert member["behavior_points"] == 8


def _setup_first_suspension_cycle(api):
    """Member suspended by a 1-day LEVEL_2 suspension starting 2026-08-03.
    Returns (site, director, member, inc1)."""
    site, director = setup_site_with_director(clock="2026-08-01T09:00:00Z")
    member = create_active_member(site["id"], director["id"], legal_name="Kid Y",
                                  date_of_birth="2011-01-01", grade=8)
    set_logical_clock("2026-08-03T10:00:00Z")
    inc1 = report_incident(member["id"], director["id"], "2026-08-03", "LEVEL_2")
    adjudicate_incident(inc1["id"], director["id"], "SUSTAINED",
                        suspension_days=1, suspension_start_date="2026-08-03")
    return site, director, member, inc1


def test_member_suspension_first_cycle_release(api):
    """PRD 3.4: "every suspension already `ACTIVE` whose full window ... has
    elapsed by the new date becomes `SERVED`, returning the member from
    `SUSPENDED` to `ACTIVE` provided no other incident still holds an `ACTIVE`
    suspension for that member."

    Design: Difficulty/non_linear_state_machine/member_suspension_cycle_reentry
    """
    site, director, member, inc1 = _setup_first_suspension_cycle(api)
    assert get_member(member["id"])["status"] == "SUSPENDED", (
        "ACTIVE -> SUSPENDED on the immediate suspension activation"
    )
    # window [2026-08-03, 2026-08-04) has elapsed by 2026-08-05
    open_club_day(site["id"], director["id"], "2026-08-05")
    assert get_member(member["id"])["status"] == "ACTIVE", (
        "SUSPENDED -> ACTIVE when the served suspension releases the member"
    )
    inc = _get_incident(api, member["id"], inc1["id"])
    assert inc["suspension_status"] == "SERVED"


def test_member_suspension_reentry_second_cycle(api):
    """PRD 3.8: "if the start date is today or earlier, the suspension becomes
    `ACTIVE` immediately and the member flips from `ACTIVE` to `SUSPENDED` on
    the spot" — re-entry into SUSPENDED on a second, independent incident is
    legal after the first suspension is served.

    Design: Difficulty/non_linear_state_machine/member_suspension_cycle_reentry
    """
    site, director, member, inc1 = _setup_first_suspension_cycle(api)
    open_club_day(site["id"], director["id"], "2026-08-05")
    assert get_member(member["id"])["status"] == "ACTIVE"

    inc2 = report_incident(member["id"], director["id"], "2026-08-05", "LEVEL_1")
    adjudicate_incident(inc2["id"], director["id"], "SUSTAINED",
                        suspension_days=1, suspension_start_date="2026-08-05")
    assert get_member(member["id"])["status"] == "SUSPENDED", (
        "re-entry into SUSPENDED proves the member cycle"
    )

    open_club_day(site["id"], director["id"], "2026-08-07")
    assert get_member(member["id"])["status"] == "ACTIVE"
    assert _get_incident(api, member["id"], inc1["id"])["suspension_status"] == "SERVED"
    assert _get_incident(api, member["id"], inc2["id"])["suspension_status"] == "SERVED"
