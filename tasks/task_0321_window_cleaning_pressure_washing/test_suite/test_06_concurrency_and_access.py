"""Optimistic-concurrency on route commitment and role-based access control.

Covers the successful version-bump commit, the stale-version rejection, the
Billing-exclusive re-clean approval boundary, and missing-auth rejection.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_account, create_property, create_sent_quote,
    setup_active_agreement, setup_requested_reclean,
    create_crew, create_route, activate_agreement, post_deposit,
    create_account_payload,
    TEST_USERS, make_customer_headers,
)

BILLING = TEST_USERS["billing_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def _first_visit(api, agreement_id):
    return api.list_agreement_visits(agreement_id, BILLING).json()["data"][0]


# ===========================================================================
# Queue B — cross_cutting_complexity_layers (OCC)
# ===========================================================================
def test_commit_with_correct_version_succeeds_and_bumps_version(api):
    """PRD §3.4: "the route's `booked_minutes` is recomputed to include the visit's
    duration, and the route's `version` increments by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_route_version_commit_succeeds_and_bumps_version
    """
    account, prop, agreement, visit = setup_active_agreement(
        schedule_kind="ONE_TIME", region_code="NORTH",
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    crew = create_crew(region_code="NORTH", skill_codes=[], daily_capacity_minutes=600)
    route = create_route(crew["id"], region_code="NORTH", service_date="2026-07-01")
    assert route["version"] == 1

    committed = validate_success(api.commit_visit(
        route["id"], {"visit_id": visit["id"], "expected_route_version": route["version"]},
        DISPATCHER), 201)
    assert committed["schedule_status"] == "SCHEDULED"
    route_after = validate_success(api.get_route(route["id"], DISPATCHER), 200)
    assert route_after["version"] == 2


def test_commit_with_stale_version_rejected(api):
    """PRD §2.9: "If that value does not equal the route's current `version` — that
    is, if another writer has committed a visit and advanced the route's version
    since the client last read it — the commit is rejected with
    `ERR_STALE_ROUTE_VERSION` and HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_route_version_commit_returns_stale_route_version
    """
    account = create_account(region_code="NORTH")
    p1 = create_property(account["id"], pane_count=60, glass_sqft=100.0, stories=2)
    q1 = create_sent_quote(account["id"], p1["id"],
                           pricing_basis="PANE_COUNT", addon_codes=["GUTTER"])
    cust = make_customer_headers(account["id"])
    validate_success(api.accept_quote(q1["id"], cust), 200)
    agr1 = validate_success(api.create_service_agreement(
        {"quote_id": q1["id"], "schedule_kind": "ONE_TIME"}, BILLING), 201)
    activate_agreement(agr1["id"], planned_date="2026-07-01",
                       window_start_min=540, window_end_min=660)
    va = _first_visit(api, agr1["id"])

    p2 = create_property(account["id"], pane_count=60, glass_sqft=100.0, stories=2)
    q2 = create_sent_quote(account["id"], p2["id"],
                           pricing_basis="PANE_COUNT", addon_codes=["GUTTER"])
    validate_success(api.accept_quote(q2["id"], cust), 200)
    agr2 = validate_success(api.create_service_agreement(
        {"quote_id": q2["id"], "schedule_kind": "ONE_TIME"}, BILLING), 201)
    activate_agreement(agr2["id"], planned_date="2026-07-01",
                       window_start_min=660, window_end_min=780)
    vb = _first_visit(api, agr2["id"])

    crew = create_crew(region_code="NORTH", skill_codes=[], daily_capacity_minutes=600)
    route = create_route(crew["id"], region_code="NORTH", service_date="2026-07-01")
    stale_version = route["version"]   # captured before any commit (== 1)

    # First commit advances route.version 1 -> 2.
    validate_success(api.commit_visit(
        route["id"], {"visit_id": va["id"], "expected_route_version": stale_version},
        DISPATCHER), 201)
    # Second commit reuses the now-stale version.
    res = api.commit_visit(
        route["id"], {"visit_id": vb["id"], "expected_route_version": stale_version},
        DISPATCHER)
    validate_error(res, "ERR_STALE_ROUTE_VERSION", expected_status=412)


# ===========================================================================
# Queue B — rbac
# ===========================================================================
def test_dispatcher_cannot_approve_reclean(api):
    """PRD §2.1: "Agreement activation and completion, invoicing and payment,
    re-clean approval and denial, and advancing the test clock are reserved to
    `Billing`."

    Design: Corner/rbac/dispatcher_cannot_approve_reclean_returns_unauthorized
    """
    account, prop, agreement, visit, reclean = setup_requested_reclean(
        region_code="NORTH", schedule_kind="ONE_TIME",
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]},
        after_photo_count=1)
    res = api.approve_reclean_request(reclean["id"], DISPATCHER)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "If either header is missing or blank, the request is rejected
    with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    res = api.create_account(create_account_payload(), headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
