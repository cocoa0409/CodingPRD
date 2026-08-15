"""Submission gates and the credit attestation boundary (PRD §3.2, §3.4)."""
from test_helpers import (
    ApiErrorId,
    B1,
    B2,
    BROKER_1_ID,
    BROKER_2_ID,
    CLOCK,
    add_certified_measurement,
    attest_credit,
    build_submitted_transfer,
    create_draft_transfer,
    get_lease,
    get_transfer,
    standard_portfolio,
    submit_transfer,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_transfer,
)


def test_transfer_initial_state_is_draft(api):
    """PRD §3.2: "Creation starts the transfer in `DRAFT` and increments the lease's `version` by one as the OCC anchor, but does not touch `open_transfer_count`; that counter moves only at submission."
    PRD §3.2: "The server records the caller's opaque identifier as the transfer's `broker_user_id`, which later bars the same broker from attesting the counterparty's credit."

    Design: Corner/state_machines/transfer_initial_state_is_draft
    """
    ctx = standard_portfolio()
    lease_v0 = ctx["lease"]["version"]
    transfer = create_draft_transfer(ctx)

    assert transfer["status"] == "DRAFT"
    assert transfer.get("submitted_at") is None
    assert transfer.get("consent_deadline") is None, "deadline is computed only at submission"
    assert transfer["broker_user_id"] == BROKER_1_ID

    lease = get_lease(ctx["lease"]["id"])
    assert lease["open_transfer_count"] == 0, "DRAFT does not move the counter"
    assert lease["version"] == lease_v0 + 1, "creation increments the lease version by one"


def test_submit_mints_consent_and_credit_review(api):
    """PRD §3.4: "A successful submission stamps `submitted_at` with the logical clock, computes the `consent_deadline`, mints exactly one consent review with `decision` of `PENDING` and exactly one credit review with `outcome` of `PENDING` for the transfer, and increments both the lease's `open_transfer_count` and its `version` by one."
    PRD §3.4: "The pass threshold is fixed at `minimum_pass_bps` of 6,000 basis points — sixty percent of the ten-thousand-point scale"

    Design: Corner/endpoints/submit_mints_consent_and_credit_review
    """
    ctx = standard_portfolio(clock=CLOCK["MONDAY_SUBMIT"])
    transfer = create_draft_transfer(ctx)
    add_certified_measurement(transfer["id"])
    submitted = submit_transfer(transfer["id"])

    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_at"] == CLOCK["MONDAY_SUBMIT"]
    assert submitted["consent_deadline"] == CLOCK["MONDAY_DEADLINE"], (
        "Mon 8/10 submission + 5 business days lands Mon 8/17 at 17:00Z"
    )

    consent, _ = validate_paginated(api.get_transfer_consent_review(transfer["id"], B1))
    assert len(consent) == 1
    assert consent[0]["decision"] == "PENDING"
    assert consent[0]["transfer_request_id"] == transfer["id"]

    credit, _ = validate_paginated(api.get_transfer_credit_review(transfer["id"], B1))
    assert len(credit) == 1
    assert credit[0]["outcome"] == "PENDING"
    assert credit[0]["minimum_pass_bps"] == 6000

    lease = get_lease(ctx["lease"]["id"])
    assert lease["open_transfer_count"] == 1


def test_submit_from_submitted_returns_invalid_state(api):
    """PRD §3.4: "The transfer must be in `DRAFT`, else `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/submit_from_submitted_returns_invalid_state
    """
    ctx = build_submitted_transfer()
    resp = api.submit_transfer_request(ctx["transfer"]["id"], B1)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_transfer(ctx["transfer"]["id"])["status"] == "SUBMITTED"


def test_marketing_period_below_30_rejected_at_submit(api):
    """PRD §3.4: "The package must be complete, else `ERR_PACKAGE_INCOMPLETE` (HTTP 422): the space must have been marketed for at least thirty days — 720 hours — so `marketing_period_days` below 30 fails, and a certified, non-superseded measurement must exist for the transfer."

    Design: Corner/validations/marketing_period_below_30_rejected_at_submit
    """
    ctx = standard_portfolio(clock=CLOCK["MONDAY_SUBMIT"])
    t1 = create_draft_transfer(ctx, marketing_period_days=29)
    add_certified_measurement(t1["id"])
    resp = api.submit_transfer_request(t1["id"], B1)
    validate_error(resp, ApiErrorId.ERR_PACKAGE_INCOMPLETE, 422)
    assert get_transfer(t1["id"])["status"] == "DRAFT"

    # Exactly 30 days meets the >= floor on a fresh lease.
    ctx2 = standard_portfolio(clock=CLOCK["MONDAY_SUBMIT"])
    t2 = create_draft_transfer(ctx2, marketing_period_days=30)
    add_certified_measurement(t2["id"])
    submitted = validate_success(api.submit_transfer_request(t2["id"], B1), 200)
    assert submitted["status"] == "SUBMITTED"


def test_term_window_inverted_rejected(api):
    """PRD §3.4: "The term window must be valid — `term_start` strictly after the logical clock's now and `term_end` strictly after `term_start` — else `ERR_TEMPORAL_WINDOW` (HTTP 422); this surface models no lease-expiry check beyond those two rules."

    Design: Corner/validations/term_window_inverted_rejected
    """
    ctx = standard_portfolio(clock=CLOCK["MONDAY_SUBMIT"])
    transfer = create_draft_transfer(
        ctx, term_start="2026-09-01T00:00:00.000Z", term_end="2026-09-01T00:00:00.000Z",
    )
    add_certified_measurement(transfer["id"])
    resp = api.submit_transfer_request(transfer["id"], B1)
    validate_error(resp, ApiErrorId.ERR_TEMPORAL_WINDOW, 422)
    assert get_transfer(transfer["id"])["status"] == "DRAFT"


def test_credit_pass_at_exact_6000(api):
    """PRD §3.4: "a reviewed rating of at least that threshold flips the review from `PENDING` to `PASS`, and anything below it flips the review to `FAIL`. Either outcome stamps `attested_at`, records the caller as `attesting_broker_user_id`, and auto-advances the transfer from `SUBMITTED` to `CONSENT_PENDING`."

    Design: Difficulty/boundary_precision_check/credit_pass_threshold_exact_6000_vs_5999
    """
    ctx = build_submitted_transfer()
    review = attest_credit(ctx["credit_review"]["id"], 6000, B2)
    assert review["outcome"] == "PASS", "6000 meets the >= 6000 threshold"
    assert review["attested_at"] is not None
    assert review["attesting_broker_user_id"] == BROKER_2_ID
    assert get_transfer(ctx["transfer"]["id"])["status"] == "CONSENT_PENDING"


def test_credit_fail_at_5999_arms_not_denies(api):
    """PRD §3.4: "a reviewed rating of at least that threshold flips the review from `PENDING` to `PASS`, and anything below it flips the review to `FAIL`."
    PRD §3.4: "A `FAIL` does not itself deny the transfer; it arms the landlord's `INSUFFICIENT_CREDIT` denial ground, nothing more."

    Design: Difficulty/boundary_precision_check/credit_pass_threshold_exact_6000_vs_5999
    """
    ctx = build_submitted_transfer()
    review = attest_credit(ctx["credit_review"]["id"], 5999, B2)
    assert review["outcome"] == "FAIL", "5999 misses the threshold by one bp"
    transfer = get_transfer(ctx["transfer"]["id"])
    assert transfer["status"] == "CONSENT_PENDING", "a FAIL arms but does not deny"


def test_broker_segregation_of_duties_attest_own_transfer(api):
    """PRD §2.9: "The broker attesting a credit review must differ from the broker who originated the transfer — the same hands that marketed the space may not vouch for the counterparty's credit."

    Design: Corner/rbac/broker_segregation_of_duties_attest_own_transfer
    """
    ctx = build_submitted_transfer()
    kr_id = ctx["credit_review"]["id"]

    resp = api.attest_credit_review(kr_id, {"reviewed_credit_rating_bps": 7000}, B1)
    validate_error(resp, ApiErrorId.ERR_DUTY_SEGREGATION, 403)
    review = validate_success(api.get_credit_review(kr_id, B1), 200)
    assert review["outcome"] == "PENDING", "rejected attestation leaves no trace"

    passed = attest_credit(kr_id, 7000, B2)
    assert passed["outcome"] == "PASS"
    assert passed["attesting_broker_user_id"] == BROKER_2_ID


def test_withdraw_only_by_originating_broker(api):
    """PRD §3.9: "Withdrawal belongs to the originating broker alone — a withdrawer whose `X-User-ID` differs from the transfer's `broker_user_id` is rejected as `ERR_DUTY_SEGREGATION`"
    PRD §3.9: "From `SUBMITTED` or `CONSENT_PENDING`, withdrawal additionally decrements that counter, increments the lease's `version`, and voids any drafted or partially-signed recognition agreement attached to the transfer."

    Design: Corner/rbac/withdraw_only_by_originating_broker
    """
    ctx = build_submitted_transfer()
    tr_id = ctx["transfer"]["id"]

    resp = api.withdraw_transfer_request(tr_id, B2)
    validate_error(resp, ApiErrorId.ERR_DUTY_SEGREGATION, 403)
    assert get_transfer(tr_id)["status"] == "SUBMITTED"

    withdrawn = withdraw_transfer(tr_id, B1)
    assert withdrawn["status"] == "WITHDRAWN"
    assert get_lease(ctx["lease"]["id"])["open_transfer_count"] == 0
