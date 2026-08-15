"""Authentication, role segregation, optimistic concurrency, and list
pagination (PRD §2.1, §2.3, §2.6)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_money,
    create_active_member,
    create_bog_for,
    create_estimate,
    create_pool_payload,
    create_season,
    create_season_payload,
    create_station,
    get_delivery,
    get_estimate,
    get_quota_for,
    make_grower_headers,
    make_station_operator_headers,
    open_season,
    patch_pool_payload,
    patch_quota_payload,
    receive_delivery,
    setup_campaign,
    setup_campaign_with_station,
    setup_received_delivery,
    setup_scheduled_delivery,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["coop_admin_headers"]
POOL_MGR = TEST_USERS["pool_manager_headers"]


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role string
    outside this enumeration, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api.create_season(create_season_payload(),
                             {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_grower_cannot_create_pool_forbidden(api):
    """PRD §2.1: "A request whose role is not permitted on the target endpoint,
    or that fails an entity-backed ownership check, is rejected with
    `ERR_FORBIDDEN`."
    PRD §4: POST /coop/pools is authorized for PoolManager only.

    Design: Corner/rbac/grower_cannot_create_pool_forbidden
    """
    member = create_active_member()
    season = create_season()

    resp = api.create_pool(create_pool_payload(season["id"]),
                           make_grower_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_grower_cannot_approve_own_estimate_forbidden(api):
    """PRD §3.3: "Review belongs to the `FieldOfficer`."
    PRD §2.1: "A request whose role is not permitted on the target endpoint,
    or that fails an entity-backed ownership check, is rejected with
    `ERR_FORBIDDEN`."

    Design: Corner/rbac/grower_cannot_approve_own_estimate_forbidden
    """
    member = create_active_member()
    bog = create_bog_for(member["id"])
    season = create_season()
    estimate = create_estimate(bog["id"], season["id"], member["id"], 2300)

    resp = api.transition_yield_estimate(estimate["id"], {"to": "APPROVED"},
                                         make_grower_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_estimate(estimate["id"])["status"] == "SUBMITTED"


def test_station_operator_cannot_grade_other_stations_delivery(api):
    """PRD §2.1: "When `X-User-Role` is `StationOperator`, `X-User-ID` is the
    `id` of the acting `ReceivingStation`; receiving and grading a delivery
    compares the delivery's `receiving_station_id` to `X-User-ID`, so an
    operator may weigh and grade only deliveries booked at their own station."

    Design: Corner/rbac/station_operator_cannot_grade_other_stations_delivery
    """
    ctx = setup_campaign_with_station()
    station_b = create_station(name="Station B")
    delivery = setup_received_delivery(ctx, 150, 50, expected_barrels=150)

    resp = api.grade_delivery(
        delivery["id"],
        {"color_score": 9.0, "firmness_score": 9.0, "foreign_matter_pct": 1.0},
        make_station_operator_headers(station_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_delivery(delivery["id"])["status"] == "RECEIVED"


def test_occ_stale_pool_version_rejected_then_fresh_accepted(api):
    """PRD §2.6: "Updating a pool's provisional advance rate (`PATCH
    /coop/pools/{id}`) requires `expected_pool_version`, carrying the pool
    `version` the client last observed."
    PRD §2.6: "If the supplied value does not match the entity's current
    `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.8: "a successful update increments the pool's `version`".

    Design: Corner/cross_cutting_layers/occ_stale_pool_version_rejected_then_fresh_accepted
    """
    season = create_season()
    resp = api.create_pool(create_pool_payload(season["id"]), POOL_MGR)
    pool = validate_success(resp, 201)
    v = pool["version"]

    stale = api.patch_pool(pool["id"], patch_pool_payload(0.60, v + 100), POOL_MGR)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    fresh = validate_success(
        api.patch_pool(pool["id"], patch_pool_payload(0.60, v), POOL_MGR), 200)
    assert_money(fresh["provisional_advance_rate_per_barrel"], 0.60)
    assert fresh["version"] == v + 1, (
        "a successful update increments the pool version by exactly 1")


def test_occ_stale_quota_version_rejected_then_fresh_accepted(api):
    """PRD §2.6: "Manually overriding a member quota (`PATCH /coop/quotas/{id}`)
    requires `expected_quota_version`, carrying the quota `version` the client
    last observed."
    PRD §2.6: "If the supplied value does not match the entity's current
    `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.3: "the override request carries the desired `base_quota_barrels`
    together with `expected_quota_version`, stores the value in
    `base_quota_override`, and recomputes the member's posture."

    Design: Corner/cross_cutting_layers/occ_stale_quota_version_rejected_then_fresh_accepted
    """
    ctx = setup_campaign()
    quota = ctx.quota
    v = quota["version"]

    stale = api.patch_quota(quota["id"], patch_quota_payload(500, v + 100), ADMIN)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    fresh = validate_success(
        api.patch_quota(quota["id"], patch_quota_payload(500, v), ADMIN), 200)
    assert_money(fresh["base_quota_barrels"], 500)
    assert_money(fresh["base_quota_override"], 500)
    assert fresh["version"] == v + 1, (
        "a successful override increments the quota version by exactly 1")


def test_deliveries_list_pagination_and_envelope_shape(api, pool_manager_headers):
    """PRD §2.3: "The `meta` object of a list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.3: "`limit` sets the maximum number of items returned: it defaults
    to 10 when omitted, with a minimum of 1 and a maximum of 100."
    PRD §3.6: "Delivery listings accept a broad filter set: `member_id`,
    `season_id`, `bog_id`, `receiving_station_id`, `main_pool_id`,
    `over_quota_pool_id`, `harvest_ticket_id`, `status`, and `scheduled_date`."

    Design: Corner/cross_cutting_layers/deliveries_list_pagination_and_envelope_shape
    """
    ctx = setup_campaign_with_station()
    for date in ("2026-10-10", "2026-10-11", "2026-10-12"):
        setup_scheduled_delivery(ctx, scheduled_date=date, expected_barrels=100)

    resp = api.list_deliveries(
        pool_manager_headers,
        params={"member_id": ctx.member["id"], "status": "SCHEDULED",
                "limit": 2, "offset": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["response_type"] == "array"
    assert isinstance(body["meta"].get("api_request_id"), str)

    data, meta = validate_paginated(resp)
    assert len(data) == 2, "limit is honored"
    assert all(d["member_id"] == ctx.member["id"] for d in data)
    assert all(d["status"] == "SCHEDULED" for d in data)
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0
