"""Role-based access control and optimistic-concurrency stale-version guards.

Covers Corner queue: rbac, cross_cutting_complexity_layers (OCC) instances.
"""

from test_helpers import (
    validate_success,
    validate_error,
    build_user_headers,
    make_customer_headers,
    create_rate_card_payload,
    create_lane_payload,
    create_customer_payload,
    create_reservation_payload,
    set_clock,
    CM, FD, LA,
)


# =============================================================================
# Corner / rbac
# =============================================================================
def test_customer_cannot_create_lane(api):
    """PRD §4: "POST /lanes | Create a lane | CenterManager".
    PRD §2.1: "A request whose role is recognized but is not permitted to perform
    the requested operation (per the authorization table in §4) is rejected with
    `ERR_FORBIDDEN`."

    Design: Corner/rbac/customer_cannot_create_lane
    """
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    resp = api.create_lane(create_lane_payload(), make_customer_headers(cust["id"]))
    validate_error(resp, "ERR_FORBIDDEN", expected_status=403)


def test_leagueadmin_cannot_check_in_reservation(api):
    """PRD §4: "POST /reservations/{id}/check-in | Check a CONFIRMED reservation in
    | FrontDesk".
    PRD §2.1: "A request whose role is recognized but is not permitted to perform
    the requested operation (per the authorization table in §4) is rejected with
    `ERR_FORBIDDEN`."

    Design: Corner/rbac/leagueadmin_cannot_check_in_reservation
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="RB2", per_game_cents=500, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    set_clock("2026-09-23T17:55:00.000Z")
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-09-23T18:00:00.000Z", end_at="2026-09-23T19:00:00.000Z",
        bowler_count=2, game_count=1), FD), 201)
    held = validate_success(api.hold_reservation(res["id"], FD), 200)
    validate_success(api.confirm_reservation(
        res["id"], {"expected_reservation_version": held["version"]}, FD), 200)

    resp = api.check_in_reservation(res["id"], LA)
    validate_error(resp, "ERR_FORBIDDEN", expected_status=403)


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "A request missing the `X-User-Role` header, or carrying a role
    outside this set, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    resp = api.list_lanes(headers={"X-User-ID": "anon", "Content-Type": "application/json"})
    validate_error(resp, "ERR_UNAUTHENTICATED", expected_status=401)


def test_customer_cannot_act_on_other_customers_reservation(api):
    """PRD §2.1: "A `Customer` who attempts to act on a reservation that is not
    theirs — that is, one whose `customer_id` does not equal `X-User-ID` — is
    rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/customer_cannot_act_on_other_customers_reservation
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="RB3", per_game_cents=500, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    c1 = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    c2 = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        c1["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-09-24T18:00:00.000Z", end_at="2026-09-24T19:00:00.000Z",
        bowler_count=2, game_count=1), make_customer_headers(c1["id"])), 201)

    resp = api.hold_reservation(res["id"], make_customer_headers(c2["id"]))
    validate_error(resp, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


# =============================================================================
# Corner / cross_cutting_complexity_layers (OCC)
# =============================================================================
def test_occ_confirm_stale_version_rejected(api):
    """PRD §2.7: "Confirming a held reservation requires the request body to carry
    `expected_reservation_version`, which must equal the reservation's current
    `version`. If another writer has advanced the reservation's `version` since the
    client last read it — for example a revise that re-priced the booking ... the
    client's view is stale and the confirm is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_confirm_stale_version_conflict
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="OCC1", per_game_cents=500, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-09-25T18:00:00.000Z", end_at="2026-09-25T19:00:00.000Z",
        bowler_count=2, game_count=2), FD), 201)
    held = validate_success(api.hold_reservation(res["id"], FD), 200)
    confirmed = validate_success(api.confirm_reservation(
        res["id"], {"expected_reservation_version": held["version"]}, FD), 200)
    # revise advances the version; the client still holds confirmed's version
    validate_success(api.revise_reservation(
        res["id"], {"expected_reservation_version": confirmed["version"], "game_count": 4}, FD), 200)

    resp = api.confirm_reservation(
        res["id"], {"expected_reservation_version": confirmed["version"]}, FD)
    validate_error(resp, "ERR_STALE_VERSION", expected_status=412)


def test_occ_revise_stale_version_rejected(api):
    """PRD §2.7: "revising a confirmed reservation requires
    `expected_reservation_version` to match the reservation's current `version`; if
    a competing revise has already superseded the booking under the revision-loop
    semantics and advanced the `version`, the current writer's view is stale and
    the revise is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_revise_stale_version_conflict
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="OCC2", per_game_cents=500, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-09-26T18:00:00.000Z", end_at="2026-09-26T19:00:00.000Z",
        bowler_count=2, game_count=2), FD), 201)
    held = validate_success(api.hold_reservation(res["id"], FD), 200)
    confirmed = validate_success(api.confirm_reservation(
        res["id"], {"expected_reservation_version": held["version"]}, FD), 200)
    # one full revise+confirm cycle advances the version past confirmed's value
    held2 = validate_success(api.revise_reservation(
        res["id"], {"expected_reservation_version": confirmed["version"], "game_count": 3}, FD), 200)
    validate_success(api.confirm_reservation(
        res["id"], {"expected_reservation_version": held2["version"]}, FD), 200)

    resp = api.revise_reservation(
        res["id"], {"expected_reservation_version": confirmed["version"], "game_count": 5}, FD)
    validate_error(resp, "ERR_STALE_VERSION", expected_status=412)
