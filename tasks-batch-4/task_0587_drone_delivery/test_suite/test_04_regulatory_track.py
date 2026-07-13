"""The regulatory track: filing the LAANC request, the authority's decision, and BVLOS
release — the second, independent state dimension of a flight."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    ApiErrorId,
    approve_authorization,
    assert_airspace_authorization,
    assert_pct,
    create_incident,
    file_authorization,
    launch_flight,
    read_authorization,
    read_flight,
    setup_approved_flight,
    setup_filed_flight,
    setup_planned_flight,
)
from test_helpers.test_users import (
    TEST_USERS,
    make_dispatch_operator_headers,
    make_flight_director_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["dispatch_operator_headers"]
DIRECTOR = TEST_USERS["flight_director_headers"]


# ==================================================== the two independent dimensions
def test_filing_and_release_advance_clearance_while_ops_state_stays_planned(api):
    """PRD §3.5: "A flight carries two entirely independent state dimensions on the same record.
    `ops_state` — `PLANNED`, `LAUNCHED`, `DROPPING`, `RETURNING`, `RECOVERED`, `ABORTED` —
    tracks where the airframe physically is. `clearance_state` — `UNFILED`, `FILED`, `CLEARED`,
    `REVOKED` — tracks the regulatory paperwork. Neither dimension advances the other."
    PRD §3.5: "Filing creates an **airspace authorization** for the flight — `flight_id` naming
    the sortie, `status` `PENDING`, `auth_code` null — moves the flight's `clearance_state`
    `UNFILED → FILED`, stamps `filed_by_user_id` with the operator's `X-User-ID`, and advances
    the flight's `version`."
    PRD §3.5: "Release moves the flight's `clearance_state` `FILED → CLEARED` and stamps
    `released_by_user_id` with the director's `X-User-ID`."

    Design: Difficulty/non_linear_state_machine/flight_parallel_ops_and_clearance_dimensions
    """
    w = setup_planned_flight()
    assert w["flight"]["ops_state"] == "PLANNED"
    assert w["flight"]["clearance_state"] == "UNFILED"

    auth = validate_success(
        api.file_authorization(
            w["flight"]["id"],
            {
                "grid_cells": ["37N122W-01"],
                "requested_alt_ft": 350,
                "window_start": "2026-06-01T08:00:00Z",
                "window_end": "2026-06-01T12:00:00Z",
            },
            OPERATOR,
        ),
        201,
    )
    assert_airspace_authorization(auth)
    assert auth["status"] == "PENDING"
    assert auth["auth_code"] is None

    after_filing = read_flight(w["flight"]["id"])
    assert after_filing["clearance_state"] == "FILED"
    assert after_filing["ops_state"] == "PLANNED", "filing must not move the physical dimension"

    approve_authorization(auth["id"])
    released = validate_success(api.release_flight(w["flight"]["id"], DIRECTOR))
    assert released["clearance_state"] == "CLEARED"
    assert released["ops_state"] == "PLANNED", "release must not move the physical dimension"


def test_launch_advances_only_ops_state_and_both_audit_stamps_survive(api):
    """PRD §3.6: "On success, four records move together. The flight goes `PLANNED → LAUNCHED`
    and its `version` advances."
    PRD §3.5: "A flight carries two entirely independent state dimensions on the same record.
    `ops_state` — `PLANNED`, `LAUNCHED`, `DROPPING`, `RETURNING`, `RECOVERED`, `ABORTED` —
    tracks where the airframe physically is. `clearance_state` — `UNFILED`, `FILED`, `CLEARED`,
    `REVOKED` — tracks the regulatory paperwork. Neither dimension advances the other."
    PRD §2.1: "It does, however, record it where the workflow demands an audit trail: the
    operator who files an airspace request is stamped onto the flight as `filed_by_user_id`, the
    director who releases it is stamped as `released_by_user_id`, and the operator who confirms
    a payload release is stamped onto the drop record as `confirmed_by_user_id`."

    Design: Difficulty/non_linear_state_machine/flight_parallel_ops_and_clearance_dimensions
    """
    w = setup_approved_flight(operator_id="op-1")
    validate_success(api.release_flight(w["flight"]["id"], make_flight_director_headers("fd-1")))

    flight = validate_success(api.launch_flight(w["flight"]["id"], OPERATOR))

    assert flight["ops_state"] == "LAUNCHED"
    assert flight["clearance_state"] == "CLEARED", (
        "launch moves the physical dimension while the regulatory one holds at CLEARED"
    )
    assert flight["filed_by_user_id"] == "op-1"
    assert flight["released_by_user_id"] == "fd-1"


# ============================================================ the LAANC authority
def test_second_laanc_decision_on_an_approved_authorization_is_rejected(api):
    """PRD §3.5: "An approval moves the authorization `PENDING → APPROVED` and mints its
    `auth_code` as the literal prefix `LAANC-` followed by the authorization's own `created_at`
    compacted to fourteen digits in the form YYYYMMDDHHMMSS."
    PRD §3.5: "A decision applied to an authorization that is not `PENDING` — one already
    approved, denied or revoked — is rejected with `ERR_AUTHORIZATION_NOT_PENDING` (HTTP 409)."

    Design: Corner/state_machines/laanc_decision_applied_twice_rejected
    """
    w = setup_approved_flight()

    resp = api.laanc_decision(
        {"authorization_id": w["auth"]["id"], "outcome": "DENIED"}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_NOT_PENDING.value)

    auth = read_authorization(w["auth"]["id"])
    assert auth["status"] == "APPROVED", "the rejected decision must not overwrite the outcome"

    data, meta = validate_paginated(
        api.list_airspace_authorizations(ADMIN, params={"flight_id": w["flight"]["id"]})
    )
    assert meta["total_count"] == 1
    assert data[0]["auth_code"] is not None, "the approval minted an auth_code"


def test_release_before_the_authority_approves_is_rejected(api):
    """PRD §3.5: "Four preconditions guard it, and they are checked in the order of §2.11: the
    flight's `clearance_state` must be `FILED` (otherwise `ERR_FLIGHT_NOT_CLEARED`, HTTP 409)
    and its `ops_state` must still be `PLANNED` (otherwise `ERR_FLIGHT_NOT_PLANNED`); the
    releasing director's `X-User-ID` must differ from the flight's `filed_by_user_id` — the same
    human may not both file and release, and an attempt to do so is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); the flight's drone must not be `GROUNDED` (otherwise
    `ERR_DRONE_GROUNDED`, HTTP 409); the drone's freshly computed `blocking_risk_score` must be
    strictly below 70.0 (otherwise `ERR_DRONE_RISK_TOO_HIGH`, HTTP 409); and the flight's
    airspace authorization must exist and be `APPROVED` (otherwise
    `ERR_AUTHORIZATION_NOT_APPROVED`, HTTP 409)."

    Design: Corner/state_machines/release_before_laanc_approval_rejected
    """
    w = setup_filed_flight()

    resp = api.release_flight(w["flight"]["id"], DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_NOT_APPROVED.value)

    flight = read_flight(w["flight"]["id"])
    assert flight["clearance_state"] == "FILED"
    assert flight["released_by_user_id"] is None

    assert read_authorization(w["auth"]["id"])["status"] == "PENDING"


# ================================================== segregation of duties and risk
def test_the_filer_may_not_release_the_flight_they_filed(api):
    """PRD §3.5: "BVLOS release is the exclusive act of a `FlightDirector`, and it is the
    segregation-of-duties point of this system. Release moves the flight's `clearance_state`
    `FILED → CLEARED` and stamps `released_by_user_id` with the director's `X-User-ID`."
    PRD §3.5: "Four preconditions guard it, and they are checked in the order of §2.11: the
    flight's `clearance_state` must be `FILED` (otherwise `ERR_FLIGHT_NOT_CLEARED`, HTTP 409)
    and its `ops_state` must still be `PLANNED` (otherwise `ERR_FLIGHT_NOT_PLANNED`); the
    releasing director's `X-User-ID` must differ from the flight's `filed_by_user_id` — the same
    human may not both file and release, and an attempt to do so is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); the flight's drone must not be `GROUNDED` (otherwise
    `ERR_DRONE_GROUNDED`, HTTP 409); the drone's freshly computed `blocking_risk_score` must be
    strictly below 70.0 (otherwise `ERR_DRONE_RISK_TOO_HIGH`, HTTP 409); and the flight's
    airspace authorization must exist and be `APPROVED` (otherwise
    `ERR_AUTHORIZATION_NOT_APPROVED`, HTTP 409)."

    Design: Corner/rbac/same_user_cannot_file_and_release_the_same_flight
    """
    w = setup_approved_flight(operator_id="u-9")

    same_user = api.release_flight(w["flight"]["id"], make_flight_director_headers("u-9"))
    validate_error(same_user, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert read_flight(w["flight"]["id"])["clearance_state"] == "FILED"

    other = validate_success(
        api.release_flight(w["flight"]["id"], make_flight_director_headers("fd-2"))
    )
    assert other["clearance_state"] == "CLEARED"
    assert other["filed_by_user_id"] == "u-9"
    assert other["released_by_user_id"] == "fd-2"


def test_release_is_blocked_when_blocking_risk_reaches_the_threshold(api):
    """PRD §3.2: "`advisory_risk_score` gates nothing whatsoever; it exists so that fleet
    dashboards can show what the airframe's risk *will* settle at once its open paperwork
    clears. `blocking_risk_score` is the number that bites: an airframe whose
    `blocking_risk_score` is 70.0 or higher is removed from the dispatch candidate set entirely,
    and a BVLOS release attempted on a flight whose drone is at or above that same threshold is
    rejected with `ERR_DRONE_RISK_TOO_HIGH` (HTTP 409). A drone strictly below 70.0 is eligible."
    PRD §3.8: "Filing has an immediate consequence: an `OPEN` incident counts toward the
    drone's `blocking_risk_score` from the moment it exists, so a `CRITICAL` incident can push
    an airframe over the 70.0 threshold and remove it from dispatch and from release the instant
    it is logged."

    Design: Difficulty/dual_variant_calc/risk_advisory_vs_blocking_on_drone
    """
    w = setup_approved_flight(
        tail_number="N102",
        hours_since_service=50,
        battery_serial="B-2",
        battery_cycle_count=150,
    )
    create_incident(
        w["drone"]["id"],
        severity="MAJOR",
        category="LOST_LINK",
        narrative="C2 link dropped on the previous sortie",
        flight_id=w["flight"]["id"],
    )

    resp = api.release_flight(w["flight"]["id"], DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_DRONE_RISK_TOO_HIGH.value)

    flight = read_flight(w["flight"]["id"])
    assert flight["clearance_state"] == "FILED", "the rejected release leaves the paperwork FILED"
    assert flight["released_by_user_id"] is None

    drone = validate_success(api.get_drone(w["drone"]["id"], ADMIN))
    # 40.0 service term + 15.0 cycle term = 55.0 advisory; + 15 MAJOR points = 70.0 blocking.
    assert_pct(drone["advisory_risk_score"], 55.0, "advisory_risk_score")
    assert_pct(drone["blocking_risk_score"], 70.0, "blocking_risk_score")
