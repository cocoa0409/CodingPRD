"""Quote acceptance: credit holds vs as-built exposure, the accept validation gauntlet,
optimistic concurrency on account version, and credit conservation on cancel."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, make_contractor_headers,
)
from test_helpers import fixtures as fx


# ==========================================================================
# dual_variant_calc / credit_provisional_hold_vs_final_asbuilt_diverges
# ==========================================================================
def test_credit_hold_provisional_diverges_from_final_after_breakage(api):
    """PRD §3.4: "The job's `credit_hold_cents` is set to the quote's `total_cents`, that
    amount is added to the account's `credit_used_cents`, and the account's `version` is
    incremented by one."
    PRD §3.8: "Recomputed on read, it is the sum, over the job's line items currently in
    `INSTALLED` status, of each such line's `line_total_cents` multiplied by one minus the
    account's tier percentage and rounded half up per line, plus the remake surcharge of
    2500 cents for each `RemakeOrder` of the job whose `billable_to_contractor` is true."

    Design: Difficulty/dual_variant_calc/credit_provisional_hold_vs_final_asbuilt_diverges
    """
    ctx = fx.setup_gold_two_line_installed(api)
    li_a = ctx["line_ids"][0]
    job_before = validate_success(api.get_job(ctx["job_id"], TEST_USERS["shop_admin_headers"]), 200)
    assert job_before["credit_hold_cents"] == 16576, job_before["credit_hold_cents"]

    claim = fx.file_claim(api, ctx["job_id"], li_a, "BREAKAGE", billable_to_contractor=True)
    validate_success(api.review_claim_report(claim["id"], {"decision": "APPROVE"},
                                             TEST_USERS["shop_admin_headers"]), 200)
    job_after = validate_success(api.get_job(ctx["job_id"], TEST_USERS["shop_admin_headers"]), 200)
    # Surviving INSTALLED line B (8288 discounted) + one billable remake surcharge 2500
    assert job_after["final_total_cents"] == 10788, job_after["final_total_cents"]
    assert job_after["final_total_cents"] != 16576


def test_final_total_equals_provisional_when_nothing_breaks(api):
    """PRD §3.8: "Recomputed on read, it is the sum, over the job's line items currently in
    `INSTALLED` status, of each such line's `line_total_cents` multiplied by one minus the
    account's tier percentage and rounded half up per line, plus the remake surcharge of
    2500 cents for each `RemakeOrder` of the job whose `billable_to_contractor` is true."

    Design: Difficulty/dual_variant_calc/credit_provisional_hold_vs_final_asbuilt_diverges
    """
    ctx = fx.setup_gold_two_line_installed(api)
    job = validate_success(api.get_job(ctx["job_id"], TEST_USERS["shop_admin_headers"]), 200)
    # Both lines INSTALLED, no remake: 8288 + 8288 == 16576 == the provisional hold
    assert job["credit_hold_cents"] == 16576, job["credit_hold_cents"]
    assert job["final_total_cents"] == 16576, job["final_total_cents"]


# ==========================================================================
# priority_pair_validation_conflict / accept_state_beats_credit_fiscal
# ==========================================================================
def test_reaccept_ordered_quote_zero_headroom_reports_invalid_state(api):
    """PRD §3.4: "Acceptance runs an ordered gauntlet of checks after authentication,
    authorization, and existence: the quote must be in `SENT` `status` (else
    `ERR_INVALID_STATE`); the owning `ContractorAccount` must be `ACTIVE` (else
    `ERR_ACCOUNT_NOT_ACTIVE`, HTTP 409); the quote must not be expired, meaning the current
    clock is at or before `valid_until` (else `ERR_QUOTE_EXPIRED`, HTTP 409); the account's
    `available_credit_cents` must be at least the quote's `total_cents` (else
    `ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 409); and finally `expected_account_version` must match
    the account's current `version` (else `ERR_STALE_ACCOUNT_VERSION`, HTTP 412)."

    Design: Difficulty/priority_pair_validation_conflict/accept_state_beats_credit_fiscal
    """
    # credit_limit exactly one quote total: after the first accept the account has zero headroom.
    account = fx.create_account(api, tier="GOLD", credit_limit_cents=16576)
    quote = fx.create_draft_quote(api, account["id"])
    fx.add_line(api, quote["id"], **fx.LINE_GOLD_ANNEALED)
    fx.add_line(api, quote["id"], **fx.LINE_GOLD_ANNEALED)
    fx.send_quote(api, quote["id"])
    fx.accept_quote(api, quote["id"], account["id"], account["version"])
    current = fx.get_account(api, account["id"])  # version now 2, headroom 0
    resp = api.accept_quote(quote["id"], {"expected_account_version": current["version"]},
                            make_contractor_headers(account["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_reaccept_ordered_quote_ample_headroom_still_invalid_state(api):
    """PRD §3.4: "Acceptance runs an ordered gauntlet of checks after authentication,
    authorization, and existence: the quote must be in `SENT` `status` (else
    `ERR_INVALID_STATE`); ...; the account's `available_credit_cents` must be at least the
    quote's `total_cents` (else `ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 409); ..."

    Design: Difficulty/priority_pair_validation_conflict/accept_state_beats_credit_fiscal
    """
    account = fx.create_account(api, tier="GOLD", credit_limit_cents=100_000_000)
    quote = fx.create_draft_quote(api, account["id"])
    fx.add_line(api, quote["id"], **fx.LINE_GOLD_ANNEALED)
    fx.add_line(api, quote["id"], **fx.LINE_GOLD_ANNEALED)
    fx.send_quote(api, quote["id"])
    fx.accept_quote(api, quote["id"], account["id"], account["version"])
    current = fx.get_account(api, account["id"])
    resp = api.accept_quote(quote["id"], {"expected_account_version": current["version"]},
                            make_contractor_headers(account["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ==========================================================================
# cross_entity_state_dependency / accept_requires_account_active
# ==========================================================================
def test_accept_suspended_account_rejected(api):
    """PRD §3.4: "the owning `ContractorAccount` must be `ACTIVE` (else
    `ERR_ACCOUNT_NOT_ACTIVE`, HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/accept_requires_account_active
    """
    account = fx.create_account(api, tier="SILVER")
    quote = fx.create_draft_quote(api, account["id"])
    fx.add_line(api, quote["id"], **fx.LINE_TABLETOP)
    fx.send_quote(api, quote["id"])
    suspended = fx.set_account_status(api, account["id"], "SUSPENDED")
    resp = api.accept_quote(quote["id"], {"expected_account_version": suspended["version"]},
                            make_contractor_headers(account["id"]))
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE)
    quote_after = validate_success(api.get_quote(quote["id"], TEST_USERS["estimator_headers"]), 200)
    assert quote_after["status"] == "SENT", quote_after["status"]


def test_accept_on_hold_account_rejected(api):
    """PRD §3.1: "An account that is not `ACTIVE` cannot have its quotes accepted (see §3.4)."
    PRD §3.4: "the owning `ContractorAccount` must be `ACTIVE` (else `ERR_ACCOUNT_NOT_ACTIVE`,
    HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/accept_requires_account_active
    """
    account = fx.create_account(api, tier="SILVER")
    quote = fx.create_draft_quote(api, account["id"])
    fx.add_line(api, quote["id"], **fx.LINE_TABLETOP)
    fx.send_quote(api, quote["id"])
    on_hold = fx.set_account_status(api, account["id"], "ON_HOLD")
    resp = api.accept_quote(quote["id"], {"expected_account_version": on_hold["version"]},
                            make_contractor_headers(account["id"]))
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE)


# ==========================================================================
# compensating_invariant / credit_used_conserved_accept_then_cancel
# ==========================================================================
def test_credit_used_returns_to_zero_after_job_cancel(api):
    """PRD §3.8: "Cancellation moves the job's `status` from `ACTIVE` to `CANCELLED` and runs
    a compensation-and-cascade sweep: the job's `credit_hold_cents` is subtracted back from
    the account's `credit_used_cents`, releasing the reservation; ..."
    PRD §3.1: "The computed `credit_used_cents` reflects the sum of `credit_hold_cents` over
    that account's `ACTIVE` jobs, and `available_credit_cents` is always `credit_limit_cents`
    minus `credit_used_cents`."

    Design: Difficulty/compensating_invariant/credit_used_conserved_accept_then_cancel
    """
    ctx = fx.setup_gold_two_line_accepted(api)
    after_accept = fx.get_account(api, ctx["account_id"])
    assert after_accept["credit_used_cents"] == 16576, after_accept["credit_used_cents"]

    cancelled = validate_success(api.cancel_job(ctx["job_id"], TEST_USERS["shop_admin_headers"]), 200)
    assert cancelled["status"] == "CANCELLED", cancelled["status"]
    after_cancel = fx.get_account(api, ctx["account_id"])
    assert after_cancel["credit_used_cents"] == 0, after_cancel["credit_used_cents"]


def test_job_cancel_releases_furnace_reservation_and_credit(api):
    """PRD §3.8: "every `SCHEDULED` tempering batch of the job is cancelled, each releasing
    its `total_sqft` from its furnace's `reserved_sqft`; and every `SCHEDULED` install
    appointment of the job is cancelled."

    Design: Difficulty/compensating_invariant/credit_used_conserved_accept_then_cancel
    """
    ctx = fx.setup_accepted_job(api, tier="SILVER", lines=[dict(fx.LINE_SHOWER_TEMPERED)])
    furnace = fx.create_furnace(api, max_batch_sqft=500)
    batch = fx.create_batch(api, ctx["job_id"], furnace["id"])
    reserved_before = validate_success(api.get_furnace(furnace["id"], TEST_USERS["fabricator_headers"]), 200)
    assert reserved_before["reserved_sqft"] == 15.0, reserved_before["reserved_sqft"]

    validate_success(api.cancel_job(ctx["job_id"], TEST_USERS["shop_admin_headers"]), 200)
    batch_after = validate_success(api.get_tempering_batch(batch["id"], TEST_USERS["fabricator_headers"]), 200)
    assert batch_after["status"] == "CANCELLED", batch_after["status"]
    furnace_after = validate_success(api.get_furnace(furnace["id"], TEST_USERS["fabricator_headers"]), 200)
    assert furnace_after["reserved_sqft"] == 0, furnace_after["reserved_sqft"]


# ==========================================================================
# validations / accept_expired_quote_returns_quote_expired
# ==========================================================================
def test_accept_expired_quote_rejected(api):
    """PRD §3.4: "the quote must not be expired, meaning the current clock is at or before
    `valid_until` (else `ERR_QUOTE_EXPIRED`, HTTP 409)."
    PRD §3.3: "The `valid_until` timestamp is stamped as the quote's `created_at` plus 30
    days."

    Design: Corner/validations/accept_expired_quote_returns_quote_expired
    """
    account = fx.create_account(api, tier="SILVER")
    quote = fx.create_draft_quote(api, account["id"])
    fx.add_line(api, quote["id"], **fx.LINE_TABLETOP)
    fx.send_quote(api, quote["id"])
    fx.set_clock(api, "2026-07-01T00:00:00Z")
    resp = api.accept_quote(quote["id"], {"expected_account_version": account["version"]},
                            make_contractor_headers(account["id"]))
    validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED)


# ==========================================================================
# validations / accept_over_credit_limit_returns_credit_exceeded
# ==========================================================================
def test_accept_over_credit_limit_rejected(api):
    """PRD §3.4: "the account's `available_credit_cents` must be at least the quote's
    `total_cents` (else `ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 409)."

    Design: Corner/validations/accept_over_credit_limit_returns_credit_exceeded
    """
    account = fx.create_account(api, tier="WALK_IN", credit_limit_cents=10000)
    quote = fx.create_draft_quote(api, account["id"])
    fx.add_line(api, quote["id"], product_type="SHOWER_ENCLOSURE", glass_type="TEMPERED",
                thickness_mm=10, width_in=30, height_in=72, quantity=1, edge_work="POLISHED")
    fx.send_quote(api, quote["id"])  # WALK_IN total 33500 > limit 10000
    resp = api.accept_quote(quote["id"], {"expected_account_version": account["version"]},
                            make_contractor_headers(account["id"]))
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


# ==========================================================================
# cross_cutting_complexity_layers / occ_stale_account_version_returns_412
# ==========================================================================
def test_accept_second_quote_with_stale_account_version_rejected(api):
    """PRD §2.7: "A subsequent accept of a *different*, still-`SENT` quote whose own fields
    are unchanged must still be rejected on this basis if the `expected_account_version` it
    carries has fallen behind the account's advanced `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_account_version_returns_412
    """
    account = fx.create_account(api, tier="SILVER")
    q_a = fx.create_draft_quote(api, account["id"])
    fx.add_line(api, q_a["id"], **fx.LINE_TABLETOP)
    fx.send_quote(api, q_a["id"])
    q_b = fx.create_draft_quote(api, account["id"])
    fx.add_line(api, q_b["id"], **fx.LINE_TABLETOP)
    fx.send_quote(api, q_b["id"])
    # Accept A with observed version 1 -> account version advances to 2
    fx.accept_quote(api, q_a["id"], account["id"], account["version"])
    # Accept B still carrying the stale version 1
    resp = api.accept_quote(q_b["id"], {"expected_account_version": account["version"]},
                            make_contractor_headers(account["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_ACCOUNT_VERSION)


# ==========================================================================
# cross_cutting_complexity_layers / version_increments_on_account_mutation
# ==========================================================================
def test_account_version_increments_on_set_status(api):
    """PRD §3.1: "The permitted transitions are `ACTIVE` to `ON_HOLD` and back, and `ACTIVE`
    to `SUSPENDED` and back; each status change increments the account's `version`."
    PRD §2.4: "`version`: an integer that starts at 1 on creation and increments by one on
    every mutation of the resource."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_account_mutation
    """
    account = fx.create_account(api, tier="SILVER")
    assert account["version"] == 1, account["version"]
    updated = validate_success(
        api.set_account_status(account["id"], {"status": "ON_HOLD"}, TEST_USERS["shop_admin_headers"]), 200)
    assert updated["version"] == 2, updated["version"]
    assert updated["status"] == "ON_HOLD", updated["status"]


# ==========================================================================
# consistency_model / accept_credit_hold_visible_immediately
# ==========================================================================
def test_credit_hold_visible_immediately_after_accept(api):
    """PRD §2.9: "When a quote is accepted, the resulting job's credit hold is added to
    `credit_used_cents`; when a job is cancelled, its hold is subtracted back; when a billable
    remake is approved, the remake surcharge is added."

    Design: Corner/consistency_model/accept_credit_hold_visible_immediately
    """
    account = fx.create_account(api, tier="WALK_IN")
    quote = fx.create_draft_quote(api, account["id"])
    fx.add_line(api, quote["id"], product_type="SHOWER_ENCLOSURE", glass_type="TEMPERED",
                thickness_mm=10, width_in=30, height_in=72, quantity=1, edge_work="POLISHED")
    fx.send_quote(api, quote["id"])
    fx.accept_quote(api, quote["id"], account["id"], account["version"])
    refreshed = validate_success(api.get_contractor_account(account["id"], TEST_USERS["shop_admin_headers"]), 200)
    assert refreshed["credit_used_cents"] == 33500, refreshed["credit_used_cents"]
