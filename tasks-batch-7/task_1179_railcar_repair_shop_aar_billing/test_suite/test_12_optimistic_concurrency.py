"""Optimistic concurrency control on the four version-guarded writes."""
from test_helpers import (
    ApiErrorId, TEST_USERS, add_car_with_inspection, add_price_entry, api_client,
    build_work_order, create_brc_for_current_wo, create_work_order_payload,
    get_railcar, get_work_order, make_car_owner_rep_headers,
    make_repair_foreman_headers, scenario_completed_wo, setup_shop_ctx,
    submit_current_wo, validate_error, validate_success,
)

ADMIN = TEST_USERS["shop_admin"]
BILLING = TEST_USERS["billing_clerk"]


def test_wo_create_with_stale_railcar_version_rejected():
    """PRD §2.11: "Creating a work order requires `expected_railcar_version`
    carrying the client's last observed `version` of the target Railcar. If the
    railcar's version has advanced since that observation — for example because
    another writer's create landed and bumped it — the create is rejected with
    `ERR_STALE_RAILCAR_VERSION` (412)".
    PRD §2.11: "Creating a work order increments the host Railcar's `version`
    by one".

    Design: Corner/cross_cutting_layers/wo_create_with_stale_railcar_version_rejected
    """
    ctx = setup_shop_ctx()
    add_car_with_inspection(ctx, car_number="8001", defects=[])
    stale_version = ctx["car"]["version"]  # captured at registration

    wo1 = validate_success(api_client.create_work_order(
        create_work_order_payload(ctx["car"]["id"], ctx["inspection"]["id"],
                                  stale_version),
        make_repair_foreman_headers("foreman-1")), expected_status=201)

    # A second writer replays the pre-create railcar version.
    resp = api_client.create_work_order(
        create_work_order_payload(ctx["car"]["id"], ctx["inspection"]["id"],
                                  stale_version, routing="MOBILE"),
        make_repair_foreman_headers("foreman-2"))
    validate_error(resp, ApiErrorId.ERR_STALE_RAILCAR_VERSION, expected_status=412)

    wo1_now = validate_success(api_client.get_work_order(wo1["id"], ADMIN))
    assert wo1_now["auth_status"] == "DRAFT", (
        "the rejected supersede attempt leaves the surviving draft intact")


def test_authorize_with_stale_estimate_version_after_revise():
    """PRD §2.11: "Authorizing a work order requires
    `expected_work_order_version` matching the work order's current `version`,
    so approval pins the exact estimate version the responsible party reviewed;
    a mismatch is rejected with `ERR_STALE_WORK_ORDER_VERSION` (412)."
    PRD §2.11: "Revising an estimate requires `expected_work_order_version`
    matching the work order's current `version`; a mismatch is rejected with
    `ERR_STALE_WORK_ORDER_VERSION` (412), so two successive re-pricing passes
    cannot silently interleave."

    Design: Corner/cross_cutting_layers/authorize_with_stale_estimate_version_after_revise
    """
    ctx = setup_shop_ctx()
    add_price_entry(ctx)
    add_car_with_inspection(ctx, car_number="8002")
    build_work_order(ctx)
    wo = submit_current_wo(ctx)
    reviewed_version = wo["version"]

    # The foreman re-estimates, advancing the version while staying pending.
    revised = validate_success(api_client.revise_estimate(
        wo["id"], {"expected_work_order_version": reviewed_version},
        make_repair_foreman_headers("foreman-1")))
    assert revised["version"] == reviewed_version + 1

    resp = api_client.authorize_work_order(
        wo["id"], {"expected_work_order_version": reviewed_version},
        make_car_owner_rep_headers(ctx["owner"]["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_WORK_ORDER_VERSION, expected_status=412)

    resp = api_client.revise_estimate(
        wo["id"], {"expected_work_order_version": reviewed_version},
        make_repair_foreman_headers("foreman-1"))
    validate_error(resp, ApiErrorId.ERR_STALE_WORK_ORDER_VERSION, expected_status=412)

    wo_now = validate_success(api_client.get_work_order(wo["id"], ADMIN))
    assert wo_now["auth_status"] == "PENDING_AUTHORIZATION"


def test_brc_create_with_stale_work_order_version_rejected():
    """PRD §2.11: "Creating a draft Billing Repair Card requires
    `expected_work_order_version` matching the work order's current `version`;
    a mismatch is rejected with `ERR_STALE_WORK_ORDER_VERSION` (412), because
    draft creation supersedes an existing draft and bumps the work order's
    version."

    Design: Corner/cross_cutting_layers/brc_create_with_stale_work_order_version_rejected
    """
    ctx = scenario_completed_wo(actual_hours=1.5)
    stale_version = get_work_order(ctx["wo"]["id"])["version"]

    create_brc_for_current_wo(ctx)  # first draft bumps the work order version
    brc1 = ctx["brc"]

    resp = api_client.create_billing_repair_card(
        {"work_order_id": ctx["wo"]["id"],
         "expected_work_order_version": stale_version}, BILLING)
    validate_error(resp, ApiErrorId.ERR_STALE_WORK_ORDER_VERSION, expected_status=412)

    brc1_now = validate_success(api_client.get_billing_repair_card(brc1["id"], ADMIN))
    assert brc1_now["status"] == "DRAFT", "the rejected create supersedes nothing"
