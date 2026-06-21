"""Action endpoints, filtered listing, RBAC denials, optimistic concurrency,
derived-field reconciliation, and immediate consistency.

Corner queue (B): sections endpoints, rbac, cross_cutting_complexity_layers,
consistency_model.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    setup_site_floor_host, setup_site_host,
    create_site, create_floor, create_host,
    create_visit, screen_visit, create_cleared_visit,
    create_contractor_pass, create_delivery,
    get_floor_version, sign_in_visit, set_clock,
    make_host_headers,
    TEST_USERS,
)

SO = TEST_USERS["security_officer_headers"]
LA = TEST_USERS["lobby_attendant_headers"]


# --- endpoints ----------------------------------------------------------

def test_pickup_delivery_marks_picked_up(api):
    """PRD 3.8: "A delivery is handed off by a `LobbyAttendant` or `Host` marking it
    picked up, which moves it `RECEIVED → PICKED_UP` — a terminal state — and stamps
    `picked_up_at` with the server clock."

    POST /deliveries/{id}/pickup on a RECEIVED delivery -> status PICKED_UP.

    Design: Corner/endpoints/pickup_delivery_action_endpoint_succeeds
    """
    set_clock("2026-06-16T09:00:00Z")
    site, host = setup_site_host()
    delivery = create_delivery(host["id"], carrier="DHL", parcel_fees_cents=[200])
    res = api.pickup_delivery(delivery["id"], make_host_headers(host["id"]))
    picked = validate_success(res)
    assert picked["status"] == "PICKED_UP", f"expected PICKED_UP, got {picked['status']}"


def test_evacuation_roster_orders_by_sign_in_time(api):
    """PRD 3.9: "it captures `roster_visit_ids` as the ordered array of `id` values of
    every visit currently in `SIGNED_IN` status on that floor, ordered by `sign_in_at`
    ascending and then by `created_at` ascending as the tie-break. The
    `roster_head_count` is the length of that snapshot array."

    Visit A signed in at 09:00, Visit B at 09:05; the evacuation snapshot has
    roster_head_count 2 and roster_visit_ids [A, B] in sign_in_at order.

    Design: Corner/endpoints/evacuation_roster_lists_signed_in_visits_in_order
    """
    set_clock("2026-06-16T09:00:00Z")
    site, floor, host = setup_site_floor_host(badge_total=5, capacity=5)
    v_a = create_cleared_visit(site["id"], host["id"], floor["id"],
                               visitor_full_name="Visitor A", visitor_company="ACo")
    sign_in_visit(v_a["id"], floor["id"])
    set_clock("2026-06-16T09:05:00Z")
    v_b = create_cleared_visit(site["id"], host["id"], floor["id"],
                               visitor_full_name="Visitor B", visitor_company="BCo")
    sign_in_visit(v_b["id"], floor["id"])

    event = validate_success(
        api.create_evacuation_event(
            {"floor_id": floor["id"], "triggered_reason": "FIRE_ALARM"}, SO
        ),
        201,
    )
    assert event["roster_head_count"] == 2, (
        f"expected roster_head_count 2, got {event['roster_head_count']}"
    )
    assert event["roster_visit_ids"] == [v_a["id"], v_b["id"]], (
        f"expected [{v_a['id']}, {v_b['id']}], got {event['roster_visit_ids']}"
    )


def test_filtered_list_visits_by_contractor_pass_id(api):
    """PRD 4 (GET /visits): "List visits, filterable by `host_id`, `floor_id`,
    `contractor_pass_id`, `room_id`, `parking_space_id`, `site_id`, `status`".
    PRD 3.3: "a `contractor_pass_id` when the visit is covered by a recurring
    contractor pass (left null for one-off visitors)".

    GET /visits?contractor_pass_id={id} returns only the covered visit.

    Design: Corner/endpoints/filtered_list_visits_by_contractor_pass_id
    """
    site, floor, host = setup_site_floor_host()
    pass_ = create_contractor_pass(host["id"])
    covered = create_visit(site["id"], host["id"], floor["id"],
                           contractor_pass_id=pass_["id"],
                           visitor_full_name="Pat Builder", visitor_company="BuildCo")
    create_visit(site["id"], host["id"], floor["id"],
                 visitor_full_name="One Off", visitor_company="OffCo")
    data, meta = validate_paginated(
        api.list_visits(SO, params={"contractor_pass_id": pass_["id"]})
    )
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    assert data[0]["id"] == covered["id"], (
        f"expected covered visit {covered['id']}, got {data[0]['id']}"
    )


# --- rbac ---------------------------------------------------------------

def test_lobby_attendant_cannot_create_watchlist_entry(api):
    """PRD 3.2: "Only `SecurityOfficer` may create, read, or list watchlist entries."
    PRD 2.1: "When the headers are well-formed but the acting role is not permitted to
    invoke the targeted endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    LobbyAttendant calling POST /watchlist-entries -> ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/lobbyattendant_cannot_create_watchlist_entry_forbidden
    """
    site = create_site(badge_total=5)
    res = api.create_watchlist_entry(
        {"site_id": site["id"], "match_type": "NAME",
         "match_value_normalized": "jane doe", "severity": "DENY"},
        LA,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_host_cannot_sign_visitor_in(api):
    """PRD 3.6: "Signing a `CLEARED` visitor in is a `LobbyAttendant` operation".
    PRD 2.1: "When the headers are well-formed but the acting role is not permitted to
    invoke the targeted endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    A Host calling POST /visits/{id}/sign-in -> ERR_FORBIDDEN_ROLE; visit stays
    CLEARED.

    Design: Corner/rbac/host_cannot_sign_visitor_in_forbidden
    """
    set_clock("2026-06-16T09:00:00Z")
    site, floor, host = setup_site_floor_host(badge_total=5, capacity=5)
    visit = create_cleared_visit(site["id"], host["id"], floor["id"],
                                 visitor_full_name="Cleared V", visitor_company="CCo")
    fv = get_floor_version(floor["id"])
    res = api.sign_in_visit(visit["id"], {"expected_floor_version": fv},
                            make_host_headers(host["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)
    fetched = validate_success(api.get_visit(visit["id"], LA))
    assert fetched["status"] == "CLEARED", f"expected CLEARED, got {fetched['status']}"


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD 2.1: "A request that omits either header, or that presents an
    `X-User-Role` value outside this set, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    GET /sites/{id} with no recognized auth headers -> ERR_UNAUTHENTICATED.

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    site = create_site(badge_total=5)
    res = api.get_site(site["id"], {})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


# --- cross-cutting complexity layers ------------------------------------

def test_stale_floor_version_on_signin_rejected(api):
    """PRD 2.8: "The sign-in request must include `expected_floor_version`, carrying
    the `version` of the target `Floor` that the attendant last observed. If that
    value does not equal the floor's current `version` — because another sign-in or
    sign-out has already changed that floor's occupancy and therefore the attendant's
    view of its `available_slots` is stale — the request is rejected with
    `ERR_STALE_FLOOR_VERSION` (HTTP 412)."

    Visit A's sign-in advances the floor version; Visit B's sign-in carrying the
    pre-advance version -> ERR_STALE_FLOOR_VERSION; B stays CLEARED.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_floor_version_on_signin
    """
    set_clock("2026-06-16T09:00:00Z")
    site, floor, host = setup_site_floor_host(badge_total=5, capacity=5)
    floor_v0 = floor["version"]
    v_a = create_cleared_visit(site["id"], host["id"], floor["id"],
                               visitor_full_name="Visitor A", visitor_company="ACo")
    v_b = create_cleared_visit(site["id"], host["id"], floor["id"],
                               visitor_full_name="Visitor B", visitor_company="BCo")
    # A signs in with the observed floor version, advancing it.
    get_success_data(api.sign_in_visit(v_a["id"], {"expected_floor_version": floor_v0}, LA))
    # B signs in carrying the now-stale pre-advance version.
    res = api.sign_in_visit(v_b["id"], {"expected_floor_version": floor_v0}, LA)
    validate_error(res, ApiErrorId.ERR_STALE_FLOOR_VERSION)
    fetched = validate_success(api.get_visit(v_b["id"], LA))
    assert fetched["status"] == "CLEARED", f"expected CLEARED, got {fetched['status']}"


def test_badge_available_recomputed_after_signin(api):
    """PRD 2.9: "For each `Site`, `badge_in_use` is the count of visits at that site
    currently in `SIGNED_IN` status, and `badge_available` is `badge_total` minus
    `badge_in_use`."
    PRD 2.9: "both are recomputed as aggregates rather than trusted as free-floating
    counters."

    After one sign-in on a badge_total-3 site, badge_in_use 1 and badge_available 2.

    Design: Corner/cross_cutting_complexity_layers/derived_badge_available_recomputed_after_signin
    """
    set_clock("2026-06-16T09:00:00Z")
    site = create_site(badge_total=3)
    floor = create_floor(site["id"], capacity=5)
    host = create_host(site["id"])
    visit = create_cleared_visit(site["id"], host["id"], floor["id"],
                                 visitor_full_name="Badge V", visitor_company="BCo")
    sign_in_visit(visit["id"], floor["id"])
    fetched_site = validate_success(api.get_site(site["id"], SO))
    assert fetched_site["badge_in_use"] == 1, (
        f"expected badge_in_use 1, got {fetched_site['badge_in_use']}"
    )
    assert fetched_site["badge_available"] == 2, (
        f"expected badge_available 2, got {fetched_site['badge_available']}"
    )


def test_host_notify_count_increments_on_prereg_and_signin(api):
    """PRD 3.3: "Pre-registering a visit fires an arrival-preparation notification: the
    visited host's `notify_count` is incremented by one."
    PRD 3.6: "The visited host's `notify_count` increases by one for the arrival."

    After one pre-registration (+1) and that visit's sign-in (+1), notify_count is 2.

    Design: Corner/cross_cutting_complexity_layers/host_notify_count_increments_on_prereg_and_signin
    """
    set_clock("2026-06-16T09:00:00Z")
    site, floor, host = setup_site_floor_host(badge_total=5, capacity=5)
    visit = create_cleared_visit(site["id"], host["id"], floor["id"],
                                 visitor_full_name="Notify V", visitor_company="NCo")
    sign_in_visit(visit["id"], floor["id"])
    fetched_host = validate_success(api.get_host(host["id"], SO))
    assert fetched_host["notify_count"] == 2, (
        f"expected notify_count 2, got {fetched_host['notify_count']}"
    )


# --- consistency model --------------------------------------------------

def test_signin_changes_visible_immediately_in_response(api):
    """PRD 3.6: "When every guard passes, the visit moves `CLEARED → SIGNED_IN`: the
    server stamps `sign_in_at` with its clock and assigns a printed `badge_number`."
    PRD 2.5: "the system applies every consequence immediately and atomically".

    The sign-in response itself shows status SIGNED_IN, a non-null badge_number, and
    sign_in_at stamped at the pinned clock value.

    Design: Corner/consistency_model/signin_changes_visible_in_same_response_immediate
    """
    set_clock("2026-06-16T09:00:00Z")
    site, floor, host = setup_site_floor_host(badge_total=5, capacity=5)
    visit = create_cleared_visit(site["id"], host["id"], floor["id"],
                                 visitor_full_name="Imm V", visitor_company="ICo")
    fv = get_floor_version(floor["id"])
    signed_in = validate_success(
        api.sign_in_visit(visit["id"], {"expected_floor_version": fv}, LA)
    )
    assert signed_in["status"] == "SIGNED_IN", f"expected SIGNED_IN, got {signed_in['status']}"
    assert signed_in["badge_number"] is not None, "badge_number must be assigned"
    assert signed_in["sign_in_at"] is not None, "sign_in_at must be stamped"
