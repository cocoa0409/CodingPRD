"""RBAC denials, authentication, and immediate-consistency corner tests
(queue B)."""
from test_helpers import (
    api_client, validate_success, validate_error,
    make_donor, make_bike, make_volunteer, make_participant,
    log_hours, set_clock,
    TEST_USERS, make_volunteer_headers, make_participant_headers,
    make_coordinator_headers,
    ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]
DIRECTOR = TEST_USERS["director_headers"]


def test_volunteer_cannot_triage():
    """PRD §2.1: "A request whose authenticated role is not in the endpoint's
    authorized list, or whose entity-backed identity does not own the targeted
    resource, is rejected with `ERR_FORBIDDEN`." (POST /bikes/{id}/triage is
    ShopCoordinator-only per PRD §4.)

    Design: Corner/rbac/volunteer_cannot_triage
    """
    d = make_donor(display_name="D RB", donor_type="INDIVIDUAL", email="drb@x.org")
    b = make_bike(d["id"], serial_number="SN-RB", bike_type="ROAD",
                  wheel_size_inches=27)
    v = make_volunteer(full_name="V R", email="vr@x.org")
    r = api_client.triage_bike(
        b["id"], {"condition_grade": "B", "frame_damage": False},
        make_volunteer_headers(v["id"]),
    )
    validate_error(r, ApiErrorId.ERR_FORBIDDEN)
    b_after = validate_success(api_client.get_bike(b["id"], COORD))
    assert b_after["status"] == "RECEIVED"


def test_participant_cannot_create_part_returns_forbidden():
    """PRD §2.1: "A request whose authenticated role is not in the endpoint's
    authorized list, or whose entity-backed identity does not own the targeted
    resource, is rejected with `ERR_FORBIDDEN`." (POST /parts is
    ShopCoordinator-only per PRD §4.)

    Design: Corner/validations/participant_cannot_create_part_returns_forbidden
    """
    p = make_participant(full_name="P RB", contact_email="prb@x.org",
                         age_group="YOUTH")
    r = api_client.create_part(
        {"name": "Forbidden part", "category": "MISC"},
        make_participant_headers(p["id"]),
    )
    validate_error(r, ApiErrorId.ERR_FORBIDDEN)


def test_missing_auth_returns_unauthenticated():
    """PRD §2.1: "A request with either header missing, or with a role value
    outside that set, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/missing_auth_returns_unauthenticated
    """
    r = api_client.create_donor(
        {"display_name": "Anon", "donor_type": "INDIVIDUAL", "email": "a@x.org"},
        headers={},
    )
    validate_error(r, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_immediate_visibility_after_approve():
    """PRD §3.7: "Approval flips the log `PENDING → APPROVED`, stamps
    `reviewed_by_user_id`, recomputes the participant's `hours_earned` as the
    sum of hours across all approved logs — pending, rejected, and voided rows
    never count — and bumps the participant's `version`."

    Design: Corner/consistency/immediate_visibility_after_approve
    """
    p = make_participant(full_name="P IV", contact_email="piv@x.org",
                         age_group="ADULT")
    set_clock("2026-08-07T00:00:00Z")
    h1 = log_hours(p["id"], "2026-08-02", 2, "SHOP_HELP")
    cur = validate_success(api_client.get_participant(p["id"], COORD))
    approved = validate_success(
        api_client.approve_hour_log(
            h1["id"], {"expected_participant_version": cur["version"]},
            make_coordinator_headers("sc-approver-1"),
        )
    )
    assert approved["status"] == "APPROVED"
    after = validate_success(api_client.get_participant(p["id"], COORD))
    assert after["hours_earned"] == 2
