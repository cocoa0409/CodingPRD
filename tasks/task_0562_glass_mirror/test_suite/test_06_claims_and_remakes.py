"""Breakage/warranty claims, the three-hop approval cascade, remake orders, and the
reverse-reachability discovery of cascade-created remake orders."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    TEST_USERS, create_claim_report_payload,
)
from test_helpers import fixtures as fx


def _line_status(api, quote_id, line_id):
    lines, _ = validate_paginated(api.list_line_items(quote_id, TEST_USERS["estimator_headers"]))
    match = [li for li in lines if li["id"] == line_id]
    assert match, f"line {line_id} not found"
    return match[0]["status"]


# ==========================================================================
# transitive_cascade / claim_approve_cascade_line_remake_credit
# ==========================================================================
def test_approve_billable_claim_cascades_line_remake_and_credit(api):
    """PRD §3.7: "First, the target line item — whether it was `INSTALLED` or `FABRICATED` —
    transitions to `BROKEN`."
    PRD §3.7: "Second, caused by that line breaking, a `RemakeOrder` is created in `PENDING`
    status: it copies the `claim_report_id`, `job_id`, `line_item_id`, and
    `billable_to_contractor` from the claim, and its `remake_cost_cents` is the line's
    `unit_price_cents` plus a remake surcharge of 2500 cents; the claim's `remake_order_id`
    is set to the new order's `id`; the job's `fabrication_status` moves from `COMPLETE` to
    `REOPENED`; and if the broken line had been `INSTALLED`, the job's `install_status` moves
    from `INSTALLED` to `ON_HOLD` and, if the job had previously `CLOSED`, its lifecycle
    `status` returns from `CLOSED` to `ACTIVE`."
    PRD §3.7: "Third, caused by the remake order's creation, if `billable_to_contractor` is
    true then the remake surcharge of 2500 cents is added both to the account's
    `credit_used_cents` and to the job's `credit_hold_cents`."

    Design: Difficulty/transitive_cascade/claim_approve_cascade_line_remake_credit
    """
    ctx = fx.setup_gold_two_line_installed(api)
    li_a = ctx["line_ids"][0]
    claim = fx.file_claim(api, ctx["job_id"], li_a, "BREAKAGE", billable_to_contractor=True)
    reviewed = validate_success(api.review_claim_report(
        claim["id"], {"decision": "APPROVE"}, TEST_USERS["shop_admin_headers"]), 200)

    assert _line_status(api, ctx["quote_id"], li_a) == "BROKEN"
    remake = validate_success(api.get_remake_order(reviewed["remake_order_id"],
                                                   TEST_USERS["fabricator_headers"]), 200)
    assert remake["remake_cost_cents"] == 12250, remake["remake_cost_cents"]  # 9750 + 2500
    job = validate_success(api.get_job(ctx["job_id"], TEST_USERS["shop_admin_headers"]), 200)
    assert job["fabrication_status"] == "REOPENED", job["fabrication_status"]
    account = fx.get_account(api, ctx["account_id"])
    assert account["credit_used_cents"] == 19076, account["credit_used_cents"]  # 16576 + 2500


def test_approve_nonbillable_claim_leaves_credit_unchanged(api):
    """PRD §3.7: "Third, caused by the remake order's creation, if `billable_to_contractor`
    is true then the remake surcharge of 2500 cents is added both to the account's
    `credit_used_cents` and to the job's `credit_hold_cents`."
    PRD §3.7: "Second, caused by that line breaking, a `RemakeOrder` is created in `PENDING`
    status: it copies the `claim_report_id`, `job_id`, `line_item_id`, and
    `billable_to_contractor` from the claim, and its `remake_cost_cents` is the line's
    `unit_price_cents` plus a remake surcharge of 2500 cents; the claim's `remake_order_id`
    is set to the new order's `id`; the job's `fabrication_status` moves from `COMPLETE` to
    `REOPENED`; and if the broken line had been `INSTALLED`, the job's `install_status` moves
    from `INSTALLED` to `ON_HOLD` and, if the job had previously `CLOSED`, its lifecycle
    `status` returns from `CLOSED` to `ACTIVE`."

    Design: Difficulty/transitive_cascade/claim_approve_cascade_line_remake_credit
    """
    ctx = fx.setup_gold_two_line_installed(api)
    li_a = ctx["line_ids"][0]
    claim = fx.file_claim(api, ctx["job_id"], li_a, "BREAKAGE", billable_to_contractor=False)
    reviewed = validate_success(api.review_claim_report(
        claim["id"], {"decision": "APPROVE"}, TEST_USERS["shop_admin_headers"]), 200)

    assert _line_status(api, ctx["quote_id"], li_a) == "BROKEN"
    remake = validate_success(api.get_remake_order(reviewed["remake_order_id"],
                                                   TEST_USERS["fabricator_headers"]), 200)
    assert remake["remake_cost_cents"] == 12250, remake["remake_cost_cents"]  # still unit + 2500
    job = validate_success(api.get_job(ctx["job_id"], TEST_USERS["shop_admin_headers"]), 200)
    assert job["fabrication_status"] == "REOPENED", job["fabrication_status"]
    assert job["install_status"] == "ON_HOLD", job["install_status"]
    account = fx.get_account(api, ctx["account_id"])
    assert account["credit_used_cents"] == 16576, account["credit_used_cents"]  # unchanged


# ==========================================================================
# state_machines / review_claim_twice_returns_invalid_state
# ==========================================================================
def test_review_already_rejected_claim_rejected(api):
    """PRD §3.7: "Only a `ShopAdmin` adjudicates a `FILED` claim by supplying a `decision` of
    `APPROVE` or `REJECT` (a claim must be `FILED` to be reviewed, else `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/review_claim_twice_returns_invalid_state
    """
    ctx = fx.setup_installed_job(api, tier="SILVER", lines=[dict(fx.LINE_SHOWER_TEMPERED)])
    claim = fx.file_claim(api, ctx["job_id"], ctx["line_ids"][0], "BREAKAGE",
                          billable_to_contractor=False)
    fx.review_claim(api, claim["id"], "REJECT")
    resp = api.review_claim_report(claim["id"], {"decision": "APPROVE"},
                                   TEST_USERS["shop_admin_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ==========================================================================
# validations / warranty_claim_after_window_returns_expired
# ==========================================================================
def test_warranty_claim_after_window_rejected(api):
    """PRD §3.7: "A `WARRANTY_DEFECT` claim is valid only within 365 days of the target
    line's installation; filed later, it is rejected with `ERR_CLAIM_WINDOW_EXPIRED` (HTTP
    409)."

    Design: Corner/validations/warranty_claim_after_window_returns_expired
    """
    ctx = fx.setup_installed_job(api, tier="SILVER", lines=[dict(fx.LINE_SHOWER_TEMPERED)])
    fx.set_clock(api, "2027-07-01T00:00:00Z")  # well beyond 365 days from install
    resp = api.create_claim_report(
        create_claim_report_payload(ctx["job_id"], ctx["line_ids"][0], "WARRANTY_DEFECT",
                                    cause="delamination"),
        TEST_USERS["scheduler_headers"])
    validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_EXPIRED)


# ==========================================================================
# validations / claim_on_spec_line_returns_target_invalid
# ==========================================================================
def test_breakage_claim_on_fabricating_line_rejected(api):
    """PRD §3.7: "The claim target must also be in a claimable line state: a
    `WARRANTY_DEFECT` requires the line to be `INSTALLED`, while a `BREAKAGE` may target a
    line that is either `FABRICATED` or `INSTALLED`; any other target state is rejected with
    `ERR_CLAIM_TARGET_INVALID` (HTTP 409)."

    Design: Corner/validations/claim_on_spec_line_returns_target_invalid
    """
    ctx = fx.setup_accepted_job(api, tier="SILVER", lines=[dict(fx.LINE_SHOWER_TEMPERED)])
    resp = api.create_claim_report(
        create_claim_report_payload(ctx["job_id"], ctx["line_ids"][0], "BREAKAGE",
                                    cause="premature", billable_to_contractor=True),
        TEST_USERS["scheduler_headers"])
    validate_error(resp, ApiErrorId.ERR_CLAIM_TARGET_INVALID)


# ==========================================================================
# endpoints / reverse_reachability_remake_orders_by_job
# ==========================================================================
def test_remake_order_discoverable_by_job_filter(api):
    """PRD §3.7: "Second, caused by that line breaking, a `RemakeOrder` is created in
    `PENDING` status: it copies the `claim_report_id`, `job_id`, `line_item_id`, and
    `billable_to_contractor` from the claim, and its `remake_cost_cents` is the line's
    `unit_price_cents` plus a remake surcharge of 2500 cents..."

    Design: Corner/endpoints/reverse_reachability_remake_orders_by_job
    """
    # ANNEALED 20x36 POLISHED shower line -> unit 9750, so remake_cost = 9750 + 2500 = 12250.
    ctx = fx.setup_installed_job(api, tier="GOLD", lines=[dict(fx.LINE_GOLD_ANNEALED)])
    claim = fx.file_claim(api, ctx["job_id"], ctx["line_ids"][0], "BREAKAGE",
                          billable_to_contractor=True)
    fx.review_claim(api, claim["id"], "APPROVE")

    remakes, meta = validate_paginated(
        api.list_remake_orders(TEST_USERS["fabricator_headers"], params={"job_id": ctx["job_id"]}))
    assert len(remakes) == 1, remakes
    assert remakes[0]["status"] == "PENDING", remakes[0]["status"]
    assert remakes[0]["remake_cost_cents"] == 12250, remakes[0]["remake_cost_cents"]
