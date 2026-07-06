"""Incident response/report dimensions, turnout point scoring, and NFIRS report
locking/amending with OCC.

Queue A: combinatorial_formula/turnout_points_tiered_role_and_officer_bonus,
non_linear_state_machine/incident_parallel_response_and_report_dimensions.
Queue B: corner_occ_report_amend_stale_incident_version,
corner_incident_arrive_from_dispatched_invalid, corner_report_before_clear_invalid,
corner_nfirs_incomplete_on_lock.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_officer,
    create_member,
    create_station_with_apparatus,
    create_cleared_incident,
    create_locked_report_incident,
    set_clock,
)
from test_helpers.factories import create_incident_payload


# --------------------------------------- turnout point scoring
def _two_turnouts_on_structure_fire(api):
    """One STRUCTURE_FIRE incident, onscene 01:00 -> cleared 03:30 (2.5h -> 3),
    with an EMT turnout and an OFFICER turnout, both RELEASED on clear."""
    off_id, off = create_officer(api)
    emt = create_member(api, role_class="EMT")
    station, apparatus = create_station_with_apparatus(api, apparatus_type="ENGINE")
    set_clock("2026-03-02T01:00:00Z")
    inc = get_success_data(
        api.create_incident(
            create_incident_payload(
                station_id=station["id"], apparatus_id=apparatus["id"],
                incident_type="STRUCTURE_FIRE", alarm_at="2026-03-02T00:50:00Z",
            ),
            off,
        )
    )
    get_success_data(api.incident_enroute(inc["id"], off))
    get_success_data(api.incident_arrive(inc["id"], off))
    t_emt = get_success_data(api.create_turnout(inc["id"], {"member_id": emt["id"]}, off))
    t_off = get_success_data(api.create_turnout(inc["id"], {"member_id": off_id}, off))
    set_clock("2026-03-02T03:30:00Z")
    get_success_data(api.incident_clear(inc["id"], off))
    return off, t_emt["id"], t_off["id"]


def test_turnout_points_emt_base_role_and_scene(api):
    """PRD §3.6: "The turnout points are the base multiplied by the role multiplier
    and rounded half up to a whole number, plus the scene component, plus the
    officer bonus."
    PRD §3.6: "The **role multiplier** is selected by the member's `role_class`:
    1.5 for `OFFICER`, 1.4 for `PARAMEDIC`, 1.2 for `EMT`, 1.0 for `FIREFIGHTER`,
    and 0.5 for `PROBATIONARY`."

    Design: Difficulty/combinatorial_formula/turnout_points_tiered_role_and_officer_bonus
    """
    off, t_emt, t_off = _two_turnouts_on_structure_fire(api)
    # base 5 * 1.2 = 6 (round) + scene min(3,6)=3 + officer bonus 0 = 9.
    turnout = validate_success(api.get_turnout(t_emt, off), 200)
    assert turnout["turnout_points"] == 9


def test_turnout_points_officer_includes_ic_bonus(api):
    """PRD §3.6: "An **officer bonus** of 2 points is added when, and only when,
    the member's `role_class` is `OFFICER`; otherwise it is zero. The turnout
    points are the base multiplied by the role multiplier and rounded half up to a
    whole number, plus the scene component, plus the officer bonus."

    Design: Difficulty/combinatorial_formula/turnout_points_tiered_role_and_officer_bonus
    """
    off, t_emt, t_off = _two_turnouts_on_structure_fire(api)
    # base 5 * 1.5 = 7.5 -> round half up 8 + scene 3 + officer bonus 2 = 13.
    turnout = validate_success(api.get_turnout(t_off, off), 200)
    assert turnout["turnout_points"] == 13


# --------------------------------------- parallel response/report dimensions
def _cleared_incident(api):
    off_id, off = create_officer(api)
    station, apparatus = create_station_with_apparatus(api, apparatus_type="ENGINE")
    inc = create_cleared_incident(api, off, station["id"], apparatus["id"], incident_type="MVA")
    return off, inc


def test_report_draft_leaves_response_cleared(api):
    """PRD §3.5: "An incident carries two independent status dimensions that
    advance separately: a response dimension and a report dimension."
    PRD §3.5: "Drafting a report advances `report_status` from `NONE` to `DRAFT`,
    permitted only when `response_status` is `CLEARED`, else `ERR_INVALID_STATE`;
    drafting saves the supplied `nfirs_property_use` and `nfirs_actions_taken`
    codes."

    Design: Difficulty/non_linear_state_machine/incident_parallel_response_and_report_dimensions
    """
    off, inc = _cleared_incident(api)
    data = validate_success(
        api.incident_report(inc["id"], {"nfirs_property_use": "419", "nfirs_actions_taken": "11"}, off), 200
    )
    assert data["report_status"] == "DRAFT"
    assert data["response_status"] == "CLEARED"


def test_report_lock_leaves_response_cleared(api):
    """PRD §3.5: "Locking a report advances `DRAFT → LOCKED` and requires that both
    `nfirs_property_use` and `nfirs_actions_taken` be present, else
    `ERR_NFIRS_INCOMPLETE`; locking increments `report_revision` by one and
    increments the incident's `version` by one."

    Design: Difficulty/non_linear_state_machine/incident_parallel_response_and_report_dimensions
    """
    off, inc = _cleared_incident(api)
    get_success_data(api.incident_report(inc["id"], {"nfirs_property_use": "419", "nfirs_actions_taken": "11"}, off))
    data = validate_success(api.incident_report_lock(inc["id"], off), 200)
    assert data["report_status"] == "LOCKED"
    assert data["response_status"] == "CLEARED"


# --------------------------------------- corner: OCC stale amend
def test_stale_report_amend_rejected_then_retry_succeeds(api):
    """PRD §2.7: "Amending a NFIRS report requires `expected_incident_version`
    matching that `Incident`'s current `version`. Because each lock or amend
    produces a new revision that supersedes the prior one, a client whose version
    is behind is editing a revision that has already been superseded; the stale
    amend is rejected with `ERR_STALE_VERSION` so a client never overwrites a
    revision it never saw."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_report_amend_stale_incident_version
    """
    off_id, off = create_officer(api)
    station, apparatus = create_station_with_apparatus(api, apparatus_type="ENGINE")
    locked = create_locked_report_incident(api, off, station["id"], apparatus["id"])
    locked_v = locked["version"]
    first = validate_success(
        api.incident_report_amend(locked["id"], {"expected_incident_version": locked_v, "nfirs_property_use": "420", "nfirs_actions_taken": "11"}, off), 200
    )
    assert first["report_status"] == "AMENDED"
    amended_v = first["version"]
    stale = api.incident_report_amend(
        locked["id"], {"expected_incident_version": locked_v, "nfirs_property_use": "421", "nfirs_actions_taken": "11"}, off
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)
    third = validate_success(
        api.incident_report_amend(locked["id"], {"expected_incident_version": amended_v, "nfirs_property_use": "422", "nfirs_actions_taken": "11"}, off), 200
    )
    assert third["report_status"] == "AMENDED"


# --------------------------------------- corner: response-sequence violation
def test_arrive_from_dispatched_rejected(api):
    """PRD §3.5: "The response dimension is a strict sequence, each step guarded by
    the requirement that the incident currently sit in the immediately preceding
    response state, failing with `ERR_INVALID_STATE` otherwise."

    Design: Corner/state_machines/corner_incident_arrive_from_dispatched_invalid
    """
    off_id, off = create_officer(api)
    station, apparatus = create_station_with_apparatus(api, apparatus_type="ENGINE")
    inc = get_success_data(
        api.create_incident(
            create_incident_payload(station_id=station["id"], apparatus_id=apparatus["id"], incident_type="EMS"), off
        )
    )
    validate_error(api.incident_arrive(inc["id"], off), ApiErrorId.ERR_INVALID_STATE.value)


# --------------------------------------- corner: report before clear
def test_report_before_clear_rejected(api):
    """PRD §3.5: "Drafting a report advances `report_status` from `NONE` to
    `DRAFT`, permitted only when `response_status` is `CLEARED`, else
    `ERR_INVALID_STATE`".

    Design: Corner/state_machines/corner_report_before_clear_invalid
    """
    off_id, off = create_officer(api)
    station, apparatus = create_station_with_apparatus(api, apparatus_type="ENGINE")
    inc = get_success_data(
        api.create_incident(
            create_incident_payload(station_id=station["id"], apparatus_id=apparatus["id"], incident_type="EMS"), off
        )
    )
    get_success_data(api.incident_enroute(inc["id"], off))
    get_success_data(api.incident_arrive(inc["id"], off))  # ONSCENE, not CLEARED
    resp = api.incident_report(inc["id"], {"nfirs_property_use": "419", "nfirs_actions_taken": "11"}, off)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --------------------------------------- corner: NFIRS incomplete on lock
def test_lock_report_missing_nfirs_rejected(api):
    """PRD §3.5: "Locking a report advances `DRAFT → LOCKED` and requires that both
    `nfirs_property_use` and `nfirs_actions_taken` be present, else
    `ERR_NFIRS_INCOMPLETE`".

    Design: Corner/validations/corner_nfirs_incomplete_on_lock
    """
    off_id, off = create_officer(api)
    station, apparatus = create_station_with_apparatus(api, apparatus_type="ENGINE")
    inc = create_cleared_incident(api, off, station["id"], apparatus["id"], incident_type="ALARM")
    get_success_data(api.incident_report(inc["id"], {}, off))  # empty draft
    validate_error(api.incident_report_lock(inc["id"], off), ApiErrorId.ERR_NFIRS_INCOMPLETE.value)
