"""Quote lifecycle: the cyclic revision loop, the design-locked precondition,
empty-line and terminal-state guards, lazy expiry, and demo-time validation.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_project_with_transformer_and_zone,
    assign_fixtures_to_zone,
    lock_design,
    build_draft_quote_with_lines,
    send_quote,
    set_clock,
    create_customer,
    create_project,
    make_customer_headers,
    api_client,
    TEST_USERS,
)
import test_helpers.factories as F

DESIGNER = TEST_USERS["lighting_designer_headers"]
ADMIN = TEST_USERS["operations_admin_headers"]


def _locked_project_with_quote(lines=None):
    if lines is None:
        lines = [{"model_code": "PATH-3W", "quantity": 1, "unit_price_cents": 4000}]
    ctx = setup_project_with_transformer_and_zone()
    assign_fixtures_to_zone(ctx, [{"model_code": "PATH-3W", "category": "PATH",
                                   "wattage_w": 3, "purchase_price_cents": 4000}])
    lock_design(ctx["project_id"])
    quote = build_draft_quote_with_lines(ctx["project_id"], lines)
    ctx["quote"] = quote
    return ctx


def test_revise_then_resend_increments_revision_round(api):
    """PRD §3.3: "A designer may cycle a quote for revision: returning a `SENT`
    quote to `DRAFT` increments its `revision_round` by one and reopens it so new
    lines can be added before re-sending."

    DRAFT->SENT->DRAFT(revise)->SENT proves the back-edge is taken: revision_round
    goes from 0 to 1.

    Design: Difficulty/non_linear_state_machine/quote_revision_cycle_increments_round
    """
    ctx = _locked_project_with_quote()
    quote_id = ctx["quote"]["id"]
    send_quote(quote_id)
    validate_success(api.revise_quote(quote_id, DESIGNER))
    resent = validate_success(api.send_quote(quote_id, DESIGNER))
    assert resent["status"] == "SENT", resent["status"]
    assert resent["revision_round"] == 1, resent["revision_round"]


def test_revise_returns_quote_to_draft(api):
    """PRD §3.3: "A designer may cycle a quote for revision: returning a `SENT`
    quote to `DRAFT` increments its `revision_round` by one and reopens it so new
    lines can be added before re-sending."

    The revise edge moves a SENT quote back to DRAFT (the back-edge of the cycle).

    Design: Difficulty/non_linear_state_machine/quote_revision_cycle_increments_round
    """
    ctx = _locked_project_with_quote()
    quote_id = ctx["quote"]["id"]
    send_quote(quote_id)
    revised = validate_success(api.revise_quote(quote_id, DESIGNER))
    assert revised["status"] == "DRAFT", revised["status"]
    assert revised["revision_round"] == 1, revised["revision_round"]


def test_send_quote_on_zoned_not_locked_project_rejected(api):
    """PRD §3.3: "sending against a project whose `design_status` is not
    `DESIGN_LOCKED` is rejected with `ERR_DESIGN_NOT_LOCKED`."

    A draft quote on a ZONED (not locked) project cannot be sent.

    Design: Difficulty/cross_entity_state_dependency/quote_send_requires_project_design_locked
    """
    ctx = setup_project_with_transformer_and_zone()
    assign_fixtures_to_zone(ctx, [{"model_code": "PATH-3W", "category": "PATH",
                                   "wattage_w": 3, "purchase_price_cents": 4000}])
    # NOTE: design intentionally NOT locked (project remains ZONED).
    quote = build_draft_quote_with_lines(
        ctx["project_id"], [{"model_code": "PATH-3W", "quantity": 1, "unit_price_cents": 4000}]
    )
    validate_error(api.send_quote(quote["id"], DESIGNER), ApiErrorId.ERR_DESIGN_NOT_LOCKED.value)


def test_send_quote_on_zoned_project_leaves_quote_draft(api):
    """PRD §3.3: "sending against a project whose `design_status` is not
    `DESIGN_LOCKED` is rejected with `ERR_DESIGN_NOT_LOCKED`."

    The rejected send leaves the quote in DRAFT (no transition occurred).

    Design: Difficulty/cross_entity_state_dependency/quote_send_requires_project_design_locked
    """
    ctx = setup_project_with_transformer_and_zone()
    assign_fixtures_to_zone(ctx, [{"model_code": "PATH-3W", "category": "PATH",
                                   "wattage_w": 3, "purchase_price_cents": 4000}])
    quote = build_draft_quote_with_lines(
        ctx["project_id"], [{"model_code": "PATH-3W", "quantity": 1, "unit_price_cents": 4000}]
    )
    validate_error(api.send_quote(quote["id"], DESIGNER), ApiErrorId.ERR_DESIGN_NOT_LOCKED.value)
    quote_now = validate_success(api.get_quote(quote["id"], DESIGNER))
    assert quote_now["status"] == "DRAFT", quote_now["status"]


def test_send_quote_with_no_lines_rejected(api):
    """PRD §3.3: "A send requires that the quote is in `DRAFT`, that it has at
    least one line (a send with zero lines is rejected with `ERR_QUOTE_NO_LINES`)".

    Design: Corner/state_machines/send_quote_with_no_lines_returns_quote_no_lines
    """
    ctx = setup_project_with_transformer_and_zone()
    assign_fixtures_to_zone(ctx, [{"model_code": "PATH-3W", "category": "PATH",
                                   "wattage_w": 3, "purchase_price_cents": 4000}])
    lock_design(ctx["project_id"])
    quote = build_draft_quote_with_lines(ctx["project_id"], lines=[])  # no lines added
    validate_error(api.send_quote(quote["id"], DESIGNER), ApiErrorId.ERR_QUOTE_NO_LINES.value)
    quote_now = validate_success(api.get_quote(quote["id"], DESIGNER))
    assert quote_now["status"] == "DRAFT", quote_now["status"]


def test_reject_already_rejected_quote_invalid_state(api):
    """PRD §3.3: "Rejection requires the quote to be `SENT` and moves it to
    `REJECTED` (terminal)."

    A second reject on a REJECTED (terminal) quote is not a defined transition.

    Design: Corner/state_machines/reject_quote_twice_terminal_lockdown
    """
    ctx = _locked_project_with_quote()
    quote_id = ctx["quote"]["id"]
    send_quote(quote_id)
    cust_headers = make_customer_headers(ctx["cust_id"])
    validate_success(api.reject_quote(quote_id, cust_headers))
    validate_error(api.reject_quote(quote_id, cust_headers), ApiErrorId.ERR_INVALID_STATE.value)
    quote_now = validate_success(api.get_quote(quote_id, DESIGNER))
    assert quote_now["status"] == "REJECTED", quote_now["status"]


def test_quote_expires_lazily_and_accept_rejected(api):
    """PRD §3.3: "A sent quote is valid for fourteen days from that send; on any
    read of the quote, or on an attempt to accept or reject it, the system lazily
    checks the clock, and if fourteen days have elapsed since the last send the
    quote transitions to `EXPIRED`. Acting on a quote that has expired this way is
    rejected with `ERR_QUOTE_EXPIRED`."

    Sent at default clock 2026-04-01; advancing 15 days expires it; accept fails.

    Design: Corner/state_machines/quote_expires_lazily_and_accept_returns_quote_expired
    """
    ctx = _locked_project_with_quote()
    quote_id = ctx["quote"]["id"]
    send_quote(quote_id)
    set_clock("2026-04-16T00:00:00Z")
    validate_error(
        api.accept_quote(quote_id, make_customer_headers(ctx["cust_id"])),
        ApiErrorId.ERR_QUOTE_EXPIRED.value,
    )
    quote_now = validate_success(api.get_quote(quote_id, DESIGNER))
    assert quote_now["status"] == "EXPIRED", quote_now["status"]


def test_create_quote_demo_requested_without_time_rejected(api):
    """PRD §3.3: "The night-demo time is mandatory whenever a demo is requested:
    if `night_demo_requested` is true but `night_demo_at` is missing, the create
    is rejected with `ERR_DEMO_TIME_REQUIRED`."

    Design: Corner/validations/demo_time_required_when_demo_requested
    """
    cust = create_customer()
    project = create_project(cust["id"])
    resp = api.create_quote(
        F.create_quote_payload(project["id"], night_demo_requested=True), DESIGNER
    )
    validate_error(resp, ApiErrorId.ERR_DEMO_TIME_REQUIRED.value)
