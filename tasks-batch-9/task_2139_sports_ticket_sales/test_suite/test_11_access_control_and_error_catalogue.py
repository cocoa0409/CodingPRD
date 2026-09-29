"""Authentication, role gating and the entity-specific not-found codes."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_account,
    create_game,
    create_plan,
    create_plan_order_payload,
    create_rep,
    create_season,
    create_season_payload,
    create_seats_payload,
    make_account_holder_headers,
    make_sales_rep_headers,
    mint_seats,
    read_plan,
    read_season,
    setup_selling_world,
    validate_error,
    validate_paginated,
    NO_AUTH_HEADERS,
    OPS_HEADERS,
    RM_HEADERS,
)


def test_request_without_auth_headers_is_unauthenticated():
    """PRD 2.1: "Every request to the API must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is absent, or if `X-User-Role` is not exactly one of the four role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing occurs."

    Design: Corner/errors/err_missing_auth_headers_returns_unauthenticated
    """
    response = api_client.create_season(create_season_payload(), NO_AUTH_HEADERS)

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    _, meta = validate_paginated(api_client.list_games(OPS_HEADERS))
    assert meta["total_count"] == 0, "nothing may be created by an unauthenticated call"


def test_role_gate_is_evaluated_before_path_parameter_existence():
    """PRD 2.9: "**Authorisation.** The caller's role is permitted for this endpoint — otherwise `ERR_UNAUTHORIZED` (403). This applies to every endpoint."
    PRD 2.9: "**Path-parameter existence,** validated left to right along the URL. A missing season is `ERR_SEASON_NOT_FOUND`, a missing game `ERR_GAME_NOT_FOUND`, a missing seat `ERR_SEAT_NOT_FOUND`, a missing plan `ERR_PLAN_NOT_FOUND`, a missing account `ERR_ACCOUNT_NOT_FOUND`, a missing order `ERR_ORDER_NOT_FOUND`, a missing hold `ERR_HOLD_NOT_FOUND`, a missing package `ERR_PACKAGE_NOT_FOUND`, a missing transfer `ERR_TRANSFER_NOT_FOUND`, and a missing service rep `ERR_REP_NOT_FOUND` — all HTTP 404."

    Design: Corner/validations/val_role_check_runs_before_existence_so_unknown_plan_returns_unauthorized
    """
    create_season()

    response = api_client.publish_season_plan(
        "22222222-3333-4444-8555-666666666666",
        make_sales_rep_headers("rep-not-real"),
    )

    error = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert error["error_id"] != ApiErrorId.ERR_PLAN_NOT_FOUND.value


def test_unknown_account_id_returns_the_account_specific_not_found_code():
    """PRD 2.9: "**Path-parameter existence,** validated left to right along the URL. A missing season is `ERR_SEASON_NOT_FOUND`, a missing game `ERR_GAME_NOT_FOUND`, a missing seat `ERR_SEAT_NOT_FOUND`, a missing plan `ERR_PLAN_NOT_FOUND`, a missing account `ERR_ACCOUNT_NOT_FOUND`, a missing order `ERR_ORDER_NOT_FOUND`, a missing hold `ERR_HOLD_NOT_FOUND`, a missing package `ERR_PACKAGE_NOT_FOUND`, a missing transfer `ERR_TRANSFER_NOT_FOUND`, and a missing service rep `ERR_REP_NOT_FOUND` — all HTTP 404."

    Design: Corner/entities/e_account_lookup_with_unknown_id_returns_account_not_found
    """
    create_account()

    response = api_client.get_account(
        "11111111-2222-4333-8444-555555555555", OPS_HEADERS
    )

    validate_error(response, ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value, 404)


def test_unknown_hold_id_returns_the_hold_specific_not_found_code():
    """PRD 2.9: "**Path-parameter existence,** validated left to right along the URL. A missing season is `ERR_SEASON_NOT_FOUND`, a missing game `ERR_GAME_NOT_FOUND`, a missing seat `ERR_SEAT_NOT_FOUND`, a missing plan `ERR_PLAN_NOT_FOUND`, a missing account `ERR_ACCOUNT_NOT_FOUND`, a missing order `ERR_ORDER_NOT_FOUND`, a missing hold `ERR_HOLD_NOT_FOUND`, a missing package `ERR_PACKAGE_NOT_FOUND`, a missing transfer `ERR_TRANSFER_NOT_FOUND`, and a missing service rep `ERR_REP_NOT_FOUND` — all HTTP 404."

    Design: Corner/errors/err_unknown_hold_id_returns_hold_not_found
    """
    create_season()

    response = api_client.get_seat_hold(
        "44444444-5555-4666-8777-888888888888", OPS_HEADERS
    )

    validate_error(response, ApiErrorId.ERR_HOLD_NOT_FOUND.value, 404)


def test_each_collection_answers_its_own_not_found_code():
    """PRD 2.9: "**Path-parameter existence,** validated left to right along the URL. A missing season is `ERR_SEASON_NOT_FOUND`, a missing game `ERR_GAME_NOT_FOUND`, a missing seat `ERR_SEAT_NOT_FOUND`, a missing plan `ERR_PLAN_NOT_FOUND`, a missing account `ERR_ACCOUNT_NOT_FOUND`, a missing order `ERR_ORDER_NOT_FOUND`, a missing hold `ERR_HOLD_NOT_FOUND`, a missing package `ERR_PACKAGE_NOT_FOUND`, a missing transfer `ERR_TRANSFER_NOT_FOUND`, and a missing service rep `ERR_REP_NOT_FOUND` — all HTTP 404."

    Design: Corner/errors/err_unknown_ids_return_entity_specific_not_found_codes
    """
    season = create_season()
    create_game(season["id"])
    mint_seats(season["id"])

    probes = [
        (api_client.get_season, "aaaaaaaa-1111-4111-8111-111111111111",
         ApiErrorId.ERR_SEASON_NOT_FOUND.value),
        (api_client.get_game, "bbbbbbbb-2222-4222-8222-222222222222",
         ApiErrorId.ERR_GAME_NOT_FOUND.value),
        (api_client.get_seat, "cccccccc-3333-4333-8333-333333333333",
         ApiErrorId.ERR_SEAT_NOT_FOUND.value),
        (api_client.get_plan_order, "dddddddd-4444-4444-8444-444444444444",
         ApiErrorId.ERR_ORDER_NOT_FOUND.value),
        (api_client.get_hospitality_package, "eeeeeeee-5555-4555-8555-555555555555",
         ApiErrorId.ERR_PACKAGE_NOT_FOUND.value),
        (api_client.get_ticket_transfer, "ffffffff-6666-4666-8666-666666666666",
         ApiErrorId.ERR_TRANSFER_NOT_FOUND.value),
        (api_client.get_service_rep, "12345678-7777-4777-8777-777777777777",
         ApiErrorId.ERR_REP_NOT_FOUND.value),
    ]
    for reader, unknown_id, expected_error in probes:
        response = reader(unknown_id, OPS_HEADERS)
        assert response.status_code == 404, (
            f"Expected 404 for {unknown_id}, got {response.status_code}"
        )
        validate_error(response, expected_error, 404)


def test_sales_rep_cannot_publish_a_season_plan():
    """PRD 2.1: "- **`RevenueManager`** — the pricing and yield owner. This role constructs and publishes plan products, decides every discount review, and decides every secondary-market request."
    PRD 4: "| POST | `/ticketing/season-plans/{plan_id}/publish` | Publish a `DRAFT` plan so orders may be written against it | RevenueManager |"
    PRD 2.9: "**Authorisation.** The caller's role is permitted for this endpoint — otherwise `ERR_UNAUTHORIZED` (403). This applies to every endpoint."

    Design: Corner/rbac/rbac_sales_rep_cannot_publish_a_season_plan
    """
    season = create_season()
    game = create_game(season["id"])
    plan = create_plan(season["id"], [game["id"]])
    rep = create_rep()

    response = api_client.publish_season_plan(
        plan["id"], make_sales_rep_headers(rep["id"])
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert read_plan(plan["id"])["plan_status"] == "DRAFT"


def test_account_holder_cannot_mint_seat_inventory():
    """PRD 2.1: "- **`TicketOpsAdmin`** — the business-operations administrator. This role builds season inventory (seasons, games, seats, service reps), opens the renewal window, drives the ops checkpoint, ingests gate scans, assigns service reps to accounts, and drives the logical clock."
    PRD 4: "| POST | `/ticketing/seats` | Bulk-mint a contiguous seat range in one section, row and zone | TicketOpsAdmin |"
    PRD 2.9: "**Authorisation.** The caller's role is permitted for this endpoint — otherwise `ERR_UNAUTHORIZED` (403). This applies to every endpoint."

    Design: Corner/rbac/rbac_account_holder_cannot_mint_seat_inventory
    """
    season = create_season()
    account = create_account()

    response = api_client.create_seats(
        create_seats_payload(season["id"], seat_number_from=1, seat_number_to=4),
        make_account_holder_headers(account["id"]),
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert read_season(season["id"])["total_seat_count"] == 0


def test_revenue_manager_cannot_create_a_plan_order():
    """PRD 3.4: "An order is built by a `SalesRep` for one of their own accounts, naming the `account_id`, the `plan_id` of the published plan being bought, the `seat_ids` array of seats requested, and an optional `discount_pct`."
    PRD 4: "| POST | `/ticketing/plan-orders` | Create a `DRAFT` plan order, freeze the quoted total and mint order holds | SalesRep |"
    PRD 2.9: "**Authorisation.** The caller's role is permitted for this endpoint — otherwise `ERR_UNAUTHORIZED` (403). This applies to every endpoint."

    Design: Corner/rbac/rbac_revenue_manager_cannot_create_a_plan_order
    """
    world = setup_selling_world()

    response = api_client.create_plan_order(
        create_plan_order_payload(
            world["account_id"], world["plan_id"], [world["seat_ids"][0]]
        ),
        RM_HEADERS,
    )

    error = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert error["error_id"] != ApiErrorId.ERR_NOT_ACCOUNT_REP.value
    assert read_season(world["season_id"])["held_seat_count"] == 0
