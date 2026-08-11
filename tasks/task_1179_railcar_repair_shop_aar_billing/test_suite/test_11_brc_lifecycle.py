"""Billing Repair Card drafting: supersession and the single-active-card rule."""
from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, create_brc_for_current_wo,
    get_work_order, scenario_completed_wo, validate_error, validate_success,
)

ADMIN = TEST_USERS["shop_admin"]
BILLING = TEST_USERS["billing_clerk"]


def test_brc_second_draft_supersedes_first():
    """PRD §3.7: "When an existing card for the same work order is still
    `DRAFT`, drafting a new one supersedes it: the old card moves to
    `SUPERSEDED` and the new card records it in `supersedes_brc_id`."

    Design: Corner/endpoints/brc_second_draft_supersedes_first
    """
    ctx = scenario_completed_wo(actual_hours=1.5)
    create_brc_for_current_wo(ctx)
    brc1 = ctx["brc"]

    wo = get_work_order(ctx["wo"]["id"])
    brc2 = validate_success(api_client.create_billing_repair_card(
        {"work_order_id": wo["id"], "expected_work_order_version": wo["version"]},
        BILLING), expected_status=201)
    assert brc2["supersedes_brc_id"] == brc1["id"], "self-referential supersede link"
    assert brc2["status"] == "DRAFT"

    old = validate_success(api_client.get_billing_repair_card(brc1["id"], ADMIN))
    assert old["status"] == "SUPERSEDED"


def test_second_brc_create_while_submitted_rejected():
    """PRD §3.7: "refuses with `ERR_BRC_ALREADY_ACTIVE` when a non-draft,
    non-terminal card already exists for the work order; such a card must be
    withdrawn before a new draft can be created."

    Design: Corner/errors/second_brc_create_while_submitted_rejected
    """
    ctx = scenario_completed_wo(actual_hours=1.5)
    create_brc_for_current_wo(ctx)
    brc1 = ctx["brc"]
    validate_success(api_client.submit_billing_repair_card(brc1["id"], BILLING))

    wo = get_work_order(ctx["wo"]["id"])
    resp = api_client.create_billing_repair_card(
        {"work_order_id": wo["id"], "expected_work_order_version": wo["version"]},
        BILLING)
    validate_error(resp, ApiErrorId.ERR_BRC_ALREADY_ACTIVE, expected_status=409)
    brc1_now = validate_success(api_client.get_billing_repair_card(brc1["id"], ADMIN))
    assert brc1_now["status"] == "SUBMITTED", "a SUBMITTED card is not supersedable"
