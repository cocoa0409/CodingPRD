"""RBAC: SchedulingPlanner exclusive operations rejected for other roles;
entity-backed CrewMember ownership; and validation priority 2 (auth) over
priority 11 (business_temporal).
"""
from test_helpers import (
    validate_error,
    set_clock,
    setup_clean_world,
    setup_scheduled_captain_assignment,
    create_crew_member,
    create_pairing,
    add_revenue_leg,
    open_bidding,
    submit_bid,
    award_pairing,
    first_assignment_for,
    get_pairing,
    make_crew_member_headers,
    TEST_USERS,
)


# ---------------------------------------------------------------------
# CrewMember cannot open bidding on a Pairing (exclusive to SchedulingPlanner)
# ---------------------------------------------------------------------

def test_crew_member_cannot_open_bidding(api):
    """PRD §2.1: "If the supplied role is not listed in the authorized roles
    for the target endpoint, the request is rejected with `ERR_FORBIDDEN`."
    PRD §4: lists `POST /pairings/{id}/open-bidding` as authorized only for
    `SchedulingPlanner`.

    Design: Corner/rbac/crew_member_cannot_open_bidding
    """
    setup_clean_world("2026-06-01T00:00:00Z")
    cm = create_crew_member(employee_code="AB0700", seniority_number=700)
    pairing = create_pairing(pairing_code="P-2026-700")
    add_revenue_leg(pairing["id"])
    res = api.open_pairing_bidding(pairing["id"], make_crew_member_headers(cm["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# ---------------------------------------------------------------------
# OperationsController cannot award a Pairing (exclusive to SchedulingPlanner)
# ---------------------------------------------------------------------

def test_operations_controller_cannot_award_pairing(api, ops_headers):
    """PRD §2.1: "If the supplied role is not listed in the authorized roles
    for the target endpoint, the request is rejected with `ERR_FORBIDDEN`."
    PRD §4: lists `POST /pairings/{id}/award` as authorized only for
    `SchedulingPlanner`.

    Design: Corner/rbac/operations_controller_cannot_award_pairing
    """
    setup_clean_world("2026-06-01T00:00:00Z")
    cm = create_crew_member(employee_code="AB0710", seniority_number=710)
    pairing = create_pairing(pairing_code="P-2026-710")
    add_revenue_leg(pairing["id"])
    open_bidding(pairing["id"])
    submit_bid(pairing["id"], cm, requested_seat="CAPTAIN")
    set_clock("2026-06-01T12:00:01Z")
    p = get_pairing(pairing["id"])
    res = api.award_pairing(
        pairing["id"],
        {"expected_pairing_version": p["version"]},
        ops_headers,
    )
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# ---------------------------------------------------------------------
# Entity-backed CrewMember: cannot act on another crew's assignment
# ---------------------------------------------------------------------

def test_crew_member_cannot_confirm_other_crews_assignment(api):
    """PRD §2.1: "Specifically, a `CrewMember` submitting a bid must use their
    own crew identity in `crew_member_id`; confirming an assignment requires
    that the assignment's `crew_member_id` equals the caller's `X-User-ID`".
    PRD §2.1 also: "Any ownership violation surfaces as `ERR_FORBIDDEN`."

    Design: Corner/rbac/crew_member_cannot_act_on_another_crews_assignment
    """
    cm_a, _pairing, assignment = setup_scheduled_captain_assignment(
        employee_code_suffix="0720", seniority_number=720
    )
    # CM_B exists but does not own assignment.
    cm_b = create_crew_member(
        employee_code="AB0721", seniority_number=721, line_type="LINEHOLDER"
    )
    res = api.confirm_assignment(
        assignment["id"], make_crew_member_headers(cm_b["id"])
    )
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# ---------------------------------------------------------------------
# Auth (priority 2) wins over business_temporal (priority 11)
# ---------------------------------------------------------------------

def test_crew_member_creating_pairing_with_bad_time_window_returns_forbidden(api):
    """PRD §2.9: "Two consequences are worth noting. First, authentication and
    authorization always precede any not-found check, so a missing-header
    caller is told they are unauthenticated even if the path id is wrong."
    PRD §2.9 list of priorities places `Authorization` at priority 2 and
    `Pairing time-window sanity` at priority 11.
    PRD §4: lists `POST /pairings` as authorized only for `SchedulingPlanner`.

    Design: Difficulty/priority_pair_validation_conflict/rbac_forbidden_vs_business_temporal_on_open_bidding
    """
    setup_clean_world("2026-06-01T00:00:00Z")
    cm = create_crew_member(employee_code="AB0090", seniority_number=90)
    # Payload also has bidding_close_utc == scheduled_start_utc which would
    # have triggered ERR_INVALID_TIME_WINDOW (priority 11). But priority 2
    # (auth) fires first because CrewMember is not authorized for POST /pairings.
    payload = {
        "pairing_code": "P-2026-090",
        "origin_base": "LAX",
        "scheduled_start_utc": "2026-06-02T00:00:00Z",
        "scheduled_end_utc": "2026-06-02T10:00:00Z",
        "required_captains": 1,
        "required_first_officers": 0,
        "required_cabin_crew": 0,
        "bidding_close_utc": "2026-06-02T00:00:00Z",
    }
    res = api.create_pairing(payload, make_crew_member_headers(cm["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)
