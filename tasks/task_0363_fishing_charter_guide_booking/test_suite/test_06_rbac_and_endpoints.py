"""Role-based access control and list-endpoint shape: unauthorized-role and
missing-user-context rejections, and the paginated charter list envelope. Covers
the corner-design rbac and endpoints instances rooted in §2.1, §2.3, and §4 of
the PRD.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    make_captain_headers,
    make_customer_headers,
    pin_clock,
    create_marina,
    create_boat,
    create_customer,
    create_charter,
    setup_scheduled_charter,
    api_client,
)
from test_helpers.fixtures import FLEET_MANAGER, DOCK_MASTER


# ===========================================================================
# Corner: rbac / customer_cannot_create_charter
# ===========================================================================

def test_customer_cannot_create_charter(api):
    """PRD §2.1: "When a well-identified user attempts an operation their role is
    not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    POST /charters is FleetManager-only (§4); a Customer caller ->
    ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/customer_cannot_create_charter
    """
    marina = create_marina(name="Rbac Marina")
    boat = create_boat(marina["id"], name="Rbacboat")
    customer = create_customer()
    res = api.create_charter(
        {"marina_id": marina["id"], "boat_id": boat["id"], "trip_type": "INSHORE",
         "depart_at": "2028-12-10T12:00:00Z", "return_at": "2028-12-10T16:00:00Z",
         "base_seat_price_cents": 10000, "seats_total": 6},
        make_customer_headers(customer["id"]),
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE")


# ===========================================================================
# Corner: rbac / dockmaster_cannot_call_weather_hold
# ===========================================================================

def test_dockmaster_cannot_call_weather_hold(api):
    """PRD §2.1: "When a well-identified user attempts an operation their role is
    not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    POST /charters/{id}/weather-hold is Captain-only (§4); a DockMaster caller ->
    ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/dockmaster_cannot_call_weather_hold
    """
    pin_clock("2029-01-01T00:00:00Z")
    ctx = setup_scheduled_charter(
        charter_overrides={"depart_at": "2029-01-10T12:00:00Z",
                           "return_at": "2029-01-10T16:00:00Z"})
    res = api.weather_hold_charter(ctx["charter"]["id"], DOCK_MASTER)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


# ===========================================================================
# Corner: rbac / missing_user_context_rejected
# ===========================================================================

def test_missing_user_context_rejected(api):
    """PRD §2.1: "Every request must carry two mandatory HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, declaring the capacity in
    which they act. A request missing either header, or carrying a malformed one,
    is rejected with `ERR_MISSING_USER_CONTEXT`."

    A request with no X-User-ID / X-User-Role headers -> ERR_MISSING_USER_CONTEXT.

    Design: Corner/rbac/missing_user_context_rejected
    """
    res = api.create_marina({"name": "NoAuth Marina", "slot_count": 2},
                            {"Content-Type": "application/json"})
    validate_error(res, "ERR_MISSING_USER_CONTEXT")


# ===========================================================================
# Corner: endpoints / list_charters_pagination_envelope
# ===========================================================================

def test_list_charters_pagination_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`,
    and `has_more` inside the `meta` object of the envelope."
    PRD §2.3: "The `limit` parameter caps the number of items returned ... it
    accepts values from a minimum of 1 to a maximum of 100."

    Two charters exist; GET /charters?limit=1&offset=0 returns total_count 2 and
    has_more true.

    Design: Corner/endpoints/list_charters_pagination_envelope
    """
    marina = create_marina(name="Page Marina")
    boat = create_boat(marina["id"], name="Pageboat")
    create_charter(marina["id"], boat["id"],
                   depart_at="2028-10-10T12:00:00Z", return_at="2028-10-10T16:00:00Z")
    create_charter(marina["id"], boat["id"], trip_type="HALF_DAY",
                   base_seat_price_cents=8000,
                   depart_at="2028-10-11T12:00:00Z", return_at="2028-10-11T16:00:00Z")
    res = api.list_charters(FLEET_MANAGER, params={"marina_id": marina["id"],
                                                   "limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2, meta["total_count"]
    assert meta["has_more"] is True, meta["has_more"]
