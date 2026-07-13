"""Quote lifecycle: the send/revise revision loop, the accept->job->line cascade,
and illegal transitions on quotes."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    TEST_USERS, make_contractor_headers,
)
from test_helpers import fixtures as fx


def _line_status(api, quote_id, line_id):
    lines, _ = validate_paginated(api.list_line_items(quote_id, TEST_USERS["estimator_headers"]))
    match = [li for li in lines if li["id"] == line_id]
    assert match, f"line {line_id} not found in quote {quote_id}"
    return match[0]["status"]


# ==========================================================================
# non_linear_state_machine / quote_revision_cycle_sent_to_draft
# ==========================================================================
def test_revise_returns_to_draft_and_increments_revision(api):
    """PRD §3.3: "Revising returns the quote's `status` from `SENT` to `DRAFT`, increments
    its `revision_number` by one, and clears `quoted_lead_days` and `valid_until` back to
    null; they are re-stamped the next time the quote is sent."

    Design: Difficulty/non_linear_state_machine/quote_revision_cycle_sent_to_draft
    """
    account = fx.create_account(api, tier="BRONZE")
    quote = fx.create_draft_quote(api, account["id"])
    fx.add_line(api, quote["id"], **fx.LINE_TABLETOP)
    fx.send_quote(api, quote["id"])
    data = validate_success(api.revise_quote(quote["id"], TEST_USERS["estimator_headers"]), 200)
    assert data["status"] == "DRAFT", data["status"]
    assert data["revision_number"] == 2, data["revision_number"]
    assert data["quoted_lead_days"] is None, data["quoted_lead_days"]


def test_revise_then_send_reenters_sent_and_restamps(api):
    """PRD §3.3: "Revising returns the quote's `status` from `SENT` to `DRAFT`, increments
    its `revision_number` by one, and clears `quoted_lead_days` and `valid_until` back to
    null; they are re-stamped the next time the quote is sent."
    PRD §3.3: "This send-and-revise loop may repeat any number of times until the quote is
    accepted."

    Design: Difficulty/non_linear_state_machine/quote_revision_cycle_sent_to_draft
    """
    account = fx.create_account(api, tier="BRONZE")
    quote = fx.create_draft_quote(api, account["id"])
    fx.add_line(api, quote["id"], **fx.LINE_TABLETOP)
    fx.send_quote(api, quote["id"])
    validate_success(api.revise_quote(quote["id"], TEST_USERS["estimator_headers"]), 200)
    resent = validate_success(api.send_quote(quote["id"], TEST_USERS["estimator_headers"]), 200)
    assert resent["status"] == "SENT", resent["status"]
    assert resent["revision_number"] == 2, resent["revision_number"]
    assert resent["quoted_lead_days"] is not None, "quoted_lead_days must be re-stamped on send"


# ==========================================================================
# transitive_cascade / quote_accept_cascade_job_lineitems
# ==========================================================================
def test_accept_orders_quote_and_fabricates_lines(api):
    """PRD §3.4: "On success, the quote transitions from `SENT` to the terminal `ORDERED`
    state and a new `Job` is created."
    PRD §3.4: "As a final cascade caused by the job's creation, every one of the quote's
    line items advances from `SPEC` to `FABRICATING`."

    Design: Difficulty/transitive_cascade/quote_accept_cascade_job_lineitems
    """
    account = fx.create_account(api, tier="SILVER")
    quote = fx.create_draft_quote(api, account["id"])
    li = fx.add_line(api, quote["id"], product_type="CUSTOM_MIRROR", glass_type="ANNEALED",
                     thickness_mm=6, width_in=30, height_in=24, quantity=1)
    fx.send_quote(api, quote["id"])
    accepted = validate_success(
        api.accept_quote(quote["id"], {"expected_account_version": account["version"]},
                         make_contractor_headers(account["id"])), 200)
    assert accepted["status"] == "ORDERED", accepted["status"]
    assert accepted["ordered_job_id"], "ordered_job_id must be set on accept"
    assert _line_status(api, quote["id"], li["id"]) == "FABRICATING"


def test_accept_creates_job_with_initial_axes_and_credit_hold(api):
    """PRD §3.4: "the job records the originating `quote_id` and `contractor_account_id`,
    and starts with lifecycle `status` `ACTIVE`, `fabrication_status` `PENDING`, and
    `install_status` `NOT_READY`; the quote's `ordered_job_id` is set to the new job's `id`."
    PRD §3.4: "The job's `credit_hold_cents` is set to the quote's `total_cents`, that
    amount is added to the account's `credit_used_cents`, and the account's `version` is
    incremented by one."

    Design: Difficulty/transitive_cascade/quote_accept_cascade_job_lineitems
    """
    account = fx.create_account(api, tier="SILVER")
    quote = fx.create_draft_quote(api, account["id"])
    fx.add_line(api, quote["id"], **fx.LINE_SHOWER_TEMPERED)
    sent = fx.send_quote(api, quote["id"])
    accepted = validate_success(
        api.accept_quote(quote["id"], {"expected_account_version": account["version"]},
                         make_contractor_headers(account["id"])), 200)
    job = validate_success(api.get_job(accepted["ordered_job_id"], TEST_USERS["shop_admin_headers"]), 200)
    assert job["status"] == "ACTIVE", job["status"]
    assert job["fabrication_status"] == "PENDING", job["fabrication_status"]
    assert job["install_status"] == "NOT_READY", job["install_status"]
    assert job["credit_hold_cents"] == sent["total_cents"], (job["credit_hold_cents"], sent["total_cents"])


# ==========================================================================
# state_machines / send_quote_from_ordered_returns_invalid_state
# ==========================================================================
def test_send_ordered_quote_rejected(api):
    """PRD §3.3: "A quote's terminal outcome is `ORDERED`; once ordered it cannot be revised
    or re-sent."
    PRD §2.8: "the target resource is in a legal state for the requested transition (for
    example, accept requires a `SENT` quote, complete requires a `SCHEDULED` batch or
    appointment, review requires a `FILED` claim), else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/send_quote_from_ordered_returns_invalid_state
    """
    ctx = fx.setup_accepted_job(api, tier="SILVER", lines=[dict(fx.LINE_TABLETOP)])
    resp = api.send_quote(ctx["quote_id"], TEST_USERS["estimator_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ==========================================================================
# state_machines / revise_quote_from_draft_returns_invalid_state
# ==========================================================================
def test_revise_draft_quote_rejected(api):
    """PRD §3.3: "A `SENT` quote can be pulled back for edits. Revising returns the quote's
    `status` from `SENT` to `DRAFT`, increments its `revision_number` by one, and clears
    `quoted_lead_days` and `valid_until` back to null; they are re-stamped the next time the
    quote is sent."
    PRD §2.8: "the target resource is in a legal state for the requested transition ... else
    `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/revise_quote_from_draft_returns_invalid_state
    """
    account = fx.create_account(api, tier="SILVER")
    quote = fx.create_draft_quote(api, account["id"])
    resp = api.revise_quote(quote["id"], TEST_USERS["estimator_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ==========================================================================
# state_machines / accept_quote_from_draft_returns_invalid_state
# ==========================================================================
def test_accept_draft_quote_rejected(api):
    """PRD §3.4: "Acceptance runs an ordered gauntlet of checks after authentication,
    authorization, and existence: the quote must be in `SENT` `status` (else
    `ERR_INVALID_STATE`)..."

    Design: Corner/state_machines/accept_quote_from_draft_returns_invalid_state
    """
    account = fx.create_account(api, tier="SILVER")
    quote = fx.create_draft_quote(api, account["id"])
    fx.add_line(api, quote["id"], **fx.LINE_TABLETOP)
    resp = api.accept_quote(quote["id"], {"expected_account_version": account["version"]},
                            make_contractor_headers(account["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ==========================================================================
# validations / send_empty_quote_returns_quote_empty
# ==========================================================================
def test_send_empty_quote_rejected(api):
    """PRD §3.3: "When the estimator sends a `DRAFT` quote, it must contain at least one line
    item; sending an empty quote is rejected with `ERR_QUOTE_EMPTY` (HTTP 422)."

    Design: Corner/validations/send_empty_quote_returns_quote_empty
    """
    account = fx.create_account(api, tier="SILVER")
    quote = fx.create_draft_quote(api, account["id"])
    resp = api.send_quote(quote["id"], TEST_USERS["estimator_headers"])
    validate_error(resp, ApiErrorId.ERR_QUOTE_EMPTY)


# ==========================================================================
# entities / create_quote_unknown_account_returns_404
# ==========================================================================
def test_create_quote_unknown_account_rejected(api):
    """PRD §2.8: "every path and body foreign-key id resolves to an existing resource. Ids
    are validated left-to-right in the order they appear in the path, then the body; the
    first unresolved id yields `ERR_NOT_FOUND` (404)."

    Design: Corner/entities/create_quote_unknown_account_returns_404
    """
    resp = api.create_quote({"contractor_account_id": "11111111-1111-4111-8111-111111111111"},
                            TEST_USERS["estimator_headers"])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
