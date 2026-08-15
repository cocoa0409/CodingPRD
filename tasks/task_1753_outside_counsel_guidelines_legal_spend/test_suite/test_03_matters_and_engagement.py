"""Matter engagement lifecycle: acceptance gates, closure, reopening (PRD §3.3)."""
from test_helpers import (
    ApiErrorId,
    assert_matter,
    create_matter,
    firm_headers,
    get_matter,
    list_line_items,
    ops_headers,
    publish_guideline_and_get_ack,
    rate_not_on_card_line,
    set_clock,
    setup_billing_ready,
    setup_department_with_firm,
    submit_invoice,
    validate_error,
    validate_success,
)


class TestEngageGatedByFirmStatus:
    """Matter PENDING → ENGAGED is gated on the engaged firm being ACTIVE."""

    def test_engage_blocked_when_firm_suspended(self, api):
        """PRD §3.3: "The engagement is accepted by the firm: a `PanelFirmUser` moves the matter `PENDING → ENGAGED`, which increments the matter's `version`. Three preconditions guard acceptance — the acting user's firm must equal the matter's `panel_firm_id` (`ERR_FIRM_MISMATCH`), the firm must be `ACTIVE` (`ERR_FIRM_NOT_ACTIVE`), and, if the department has any currently `PUBLISHED` guideline version, the firm must hold an `ACKNOWLEDGED` acknowledgment for it (`ERR_ACK_OUTSTANDING`)."

        Design: Difficulty/cross_entity_state_dependency/matter_engage_gated_by_firm_status
        """
        dept, firm = setup_department_with_firm()
        matter = create_matter(dept["id"], firm["id"], title="M X", budget_cents=1_000_000)
        validate_success(api.suspend_panel_firm(dept["id"], firm["id"], ops_headers()))

        resp = api.engage_matter(dept["id"], matter["id"], firm_headers(firm["id"]))
        validate_error(resp, ApiErrorId.ERR_FIRM_NOT_ACTIVE)
        after = get_matter(dept["id"], matter["id"])
        assert after["engagement_status"] == "PENDING", (
            f"failed engage must leave the matter PENDING, got {after['engagement_status']}"
        )

    def test_engage_succeeds_after_reinstate(self, api):
        """PRD §3.1: "a `LegalOpsReviewer` may move a firm `ACTIVE → SUSPENDED`, which blocks new invoices and new rate cards; a suspended firm may be reinstated `SUSPENDED → ACTIVE`"
        PRD §3.3: "The engagement is accepted by the firm: a `PanelFirmUser` moves the matter `PENDING → ENGAGED`, which increments the matter's `version`. Three preconditions guard acceptance — the acting user's firm must equal the matter's `panel_firm_id` (`ERR_FIRM_MISMATCH`), the firm must be `ACTIVE` (`ERR_FIRM_NOT_ACTIVE`), and, if the department has any currently `PUBLISHED` guideline version, the firm must hold an `ACKNOWLEDGED` acknowledgment for it (`ERR_ACK_OUTSTANDING`)."

        Design: Difficulty/cross_entity_state_dependency/matter_engage_gated_by_firm_status
        """
        dept, firm = setup_department_with_firm()
        matter = create_matter(dept["id"], firm["id"], title="M X", budget_cents=1_000_000)
        validate_success(api.suspend_panel_firm(dept["id"], firm["id"], ops_headers()))
        validate_success(api.reinstate_panel_firm(dept["id"], firm["id"], ops_headers()))

        engaged = validate_success(api.engage_matter(dept["id"], matter["id"], firm_headers(firm["id"])))
        assert_matter(engaged)
        assert engaged["engagement_status"] == "ENGAGED", (
            f"engage must succeed once the firm is ACTIVE again, got {engaged['engagement_status']}"
        )


def test_engage_already_engaged_matter_returns_invalid_state(api):
    """PRD §3.3: "The engagement is accepted by the firm: a `PanelFirmUser` moves the matter `PENDING → ENGAGED`, which increments the matter's `version`."
    PRD §2.9: "4. State legality: the target resource is in a state from which the requested transition is permitted — otherwise `ERR_INVALID_STATE`."

    Design: Corner/state_machines/engage_already_engaged_matter_returns_invalid_state
    """
    dept, firm = setup_department_with_firm()
    matter = create_matter(dept["id"], firm["id"], title="M", budget_cents=1000)
    validate_success(api.engage_matter(dept["id"], matter["id"], firm_headers(firm["id"])))

    resp = api.engage_matter(dept["id"], matter["id"], firm_headers(firm["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_matter_close_reopen_cycle(api, legal_ops_headers):
    """PRD §3.3: "Closure and reopening belong to the `LegalOpsReviewer`. Closing a matter (`ENGAGED → CLOSED`) is refused with `ERR_MATTER_HAS_OPEN_INVOICES` while any of its invoices sits in `SUBMITTED` or `UNDER_REVIEW`, and refused with `ERR_MATTER_HAS_OPEN_APPEALS` while any appeal on any of its line items sits in `SUBMITTED` or `UNDER_REVIEW`. A closed matter is not strictly terminal: reopening returns it `CLOSED → ENGAGED`, provided the engaged firm is `ACTIVE` (`ERR_FIRM_NOT_ACTIVE`)."

    Design: Corner/state_machines/matter_close_reopen_cycle
    """
    dept, firm = setup_department_with_firm()
    matter = create_matter(dept["id"], firm["id"], title="M", budget_cents=1000)
    validate_success(api.engage_matter(dept["id"], matter["id"], firm_headers(firm["id"])))

    closed = validate_success(api.close_matter(dept["id"], matter["id"], legal_ops_headers))
    assert closed["engagement_status"] == "CLOSED"
    reopened = validate_success(api.reopen_matter(dept["id"], matter["id"], legal_ops_headers))
    assert reopened["engagement_status"] == "ENGAGED", (
        f"reopen must return the matter to ENGAGED, got {reopened['engagement_status']}"
    )


def test_close_matter_with_open_invoice_blocked(api, legal_ops_headers):
    """PRD §3.3: "Closing a matter (`ENGAGED → CLOSED`) is refused with `ERR_MATTER_HAS_OPEN_INVOICES` while any of its invoices sits in `SUBMITTED` or `UNDER_REVIEW`"
    PRD §3.5: "Otherwise, if the asserted rate matches no approved rate on the firm's card for that year yet sits below the approved rate, the line is left `PENDING` for manual review — the rate-not-on-card case."

    Design: Corner/state_machines/close_matter_with_open_invoice_blocked
    """
    ctx = setup_billing_ready()
    dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
    invoice = submit_invoice(
        dept_id, ctx["matter"]["id"], firm_id, ctx["matter_version"],
        [rate_not_on_card_line(ctx["timekeeper"]["id"], "L110", 1.00, 90_000)],
        invoice_number="INV-OPEN",
    )
    lines = list_line_items(dept_id, ctx["matter"]["id"], invoice["id"])
    assert lines[0]["review_status"] == "PENDING", "rate-not-on-card line must remain PENDING"

    resp = api.close_matter(dept_id, ctx["matter"]["id"], legal_ops_headers)
    validate_error(resp, ApiErrorId.ERR_MATTER_HAS_OPEN_INVOICES)


def test_error_ack_outstanding_blocks_engage(api):
    """PRD §3.3: "Three preconditions guard acceptance — the acting user's firm must equal the matter's `panel_firm_id` (`ERR_FIRM_MISMATCH`), the firm must be `ACTIVE` (`ERR_FIRM_NOT_ACTIVE`), and, if the department has any currently `PUBLISHED` guideline version, the firm must hold an `ACKNOWLEDGED` acknowledgment for it (`ERR_ACK_OUTSTANDING`)."

    Design: Corner/errors/error_ack_outstanding_blocks_engage
    """
    set_clock("2026-08-01T00:00:00Z")
    dept, firm = setup_department_with_firm()
    publish_guideline_and_get_ack(dept["id"], firm["id"])
    matter = create_matter(dept["id"], firm["id"], title="M", budget_cents=1000)

    resp = api.engage_matter(dept["id"], matter["id"], firm_headers(firm["id"]))
    validate_error(resp, ApiErrorId.ERR_ACK_OUTSTANDING)
    after = get_matter(dept["id"], matter["id"])
    assert after["engagement_status"] == "PENDING"
