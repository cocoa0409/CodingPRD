"""Quote presentation dimension: revision loop, invalid-state guards, ownership,
and the optimistic-concurrency guard on quote creation.

Queue A (difficulty): none directly here (OCC positive path lives in test_03).
Queue B (corner): state_machines, validations, cross_cutting_complexity_layers.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    make_customer_headers, make_designer_headers,
    create_quote_payload,
    setup_design_complete_project, setup_presented_quote, create_quote_on,
    create_customer, get_project_version,
)

IC = TEST_USERS["install_coordinator_headers"]


def test_request_revision_cycles_quote_and_reverts_project(api):
    """PRD §3.3: "Requesting a revision moves the quote PRESENTED →
    REVISION_REQUESTED, increments its revision_round by one, and drops the
    project back QUOTED → DESIGN_COMPLETE so the designer can author a fresh,
    superseding quote."

    Design: Corner/state_machines/quote_request_revision_cycle_bumps_round_and_reverts_project
    """
    ctx = setup_presented_quote(api, area=100.0, wall_system="TILE_LOOK_ACRYLIC")
    validate_success(api.request_revision(
        ctx["quote"]["id"], make_customer_headers(ctx["customer"]["id"])), 200)
    quote = validate_success(api.get_quote(ctx["quote"]["id"], IC), 200)
    project = validate_success(api.get_project(ctx["project"]["id"], IC), 200)
    assert quote["status"] == "REVISION_REQUESTED"
    assert quote["revision_round"] == 1, f"revision_round must be 1, got {quote['revision_round']}"
    assert project["status"] == "DESIGN_COMPLETE"


def test_accept_draft_quote_rejected(api):
    """PRD §3.5: "Acceptance is allowed only by the project's owner
    (ERR_NOT_RESOURCE_OWNER), only while the quote is PRESENTED
    (ERR_QUOTE_INVALID_STATE), and only when the quote's financing_status is
    either NONE (pay-in-full) or APPROVED; a quote whose financing is still
    REQUESTED or was DECLINED cannot be accepted and is refused with
    ERR_FINANCING_NOT_APPROVED."

    Design: Corner/state_machines/quote_accept_from_draft_returns_invalid_state
    """
    ctx = setup_design_complete_project(api, area=100.0)
    quote = create_quote_on(api, ctx, wall_system="TILE_LOOK_ACRYLIC")  # DRAFT, never presented
    resp = api.accept_quote(quote["id"], make_customer_headers(ctx["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_QUOTE_INVALID_STATE.value)


def test_stale_project_version_on_quote_create_rejected(api):
    """PRD §2.8: "If expected_project_version does not equal the project's current
    version — for instance because another writer has since created a superseding
    quote and thereby advanced the project's version — the creation is rejected
    with ERR_STALE_PROJECT_VERSION (HTTP 412), and the client must re-read the
    project before retrying."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_project_version_on_quote_create_rejected
    """
    ctx = setup_design_complete_project(api, area=100.0)
    stale_version = get_project_version(api, ctx["project"]["id"])
    des_headers = make_designer_headers(ctx["designer"]["id"])
    # First create succeeds and advances the project version.
    validate_success(api.create_quote(
        create_quote_payload(ctx["project"]["id"], stale_version,
                             wall_system="TILE_LOOK_ACRYLIC"), des_headers), 201)
    # Second create still carrying the pre-create version is stale.
    resp = api.create_quote(
        create_quote_payload(ctx["project"]["id"], stale_version,
                             wall_system="STONE_LOOK_ACRYLIC", color="BONE"), des_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_PROJECT_VERSION.value)


def test_non_owner_customer_cannot_accept_quote(api):
    """PRD §3.5: "Acceptance is allowed only by the project's owner
    (ERR_NOT_RESOURCE_OWNER), only while the quote is PRESENTED
    (ERR_QUOTE_INVALID_STATE), and only when the quote's financing_status is
    either NONE (pay-in-full) or APPROVED; a quote whose financing is still
    REQUESTED or was DECLINED cannot be accepted and is refused with
    ERR_FINANCING_NOT_APPROVED."

    Design: Corner/validations/customer_accept_other_customers_quote_denied
    """
    ctx = setup_presented_quote(api, area=100.0, wall_system="TILE_LOOK_ACRYLIC")
    other = create_customer(api)
    resp = api.accept_quote(ctx["quote"]["id"], make_customer_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
