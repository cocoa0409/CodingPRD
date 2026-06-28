"""Contributions and the IRS guardrail: posting, the pinned recompute order,
posture locking, catch-up eligibility and sub-limit, payroll gating.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
)
from test_helpers.fixtures import (
    ADMIN, set_clock, create_accountholder, create_employer, open_account,
    attest_coverage, verify_account, setup_active_account,
    setup_active_account_with_cash, create_contribution, post_contribution,
    create_and_post_contribution,
)

ADMIN_HDR = ADMIN


# ── contribution_accrual_pinned_eval_order (Difficulty/combinatorial_formula) ─

def test_post_to_exact_limit_leaves_zero_excess_open_posture(api):
    """PRD §3.4: "First, `contributions_ytd_cents` is set to the sum of `amount_cents`
    over all `POSTED` contributions in the plan year. Second, `applicable_limit_cents`
    is taken from the active limit variant (which depends on coverage, not on
    contributions)."
    PRD §3.4: "After the catch-up guard, `excess_contribution_cents` is set to the
    greater of zero and `contributions_ytd_cents` minus `applicable_limit_cents`."

    SELF_ONLY full year -> LMR limit 432000. Posting exactly 432000 leaves excess 0,
    posture OPEN.

    Design: Difficulty/combinatorial_formula/contribution_accrual_pinned_eval_order
    """
    account, holder = setup_active_account(coverage_tier="SELF_ONLY",
                                           date_of_birth="1979-09-09",
                                           clock="2026-03-01T00:00:00Z")
    contrib = create_contribution(account["id"], "INDIVIDUAL", 432000)
    post_contribution(account["id"], contrib["id"])
    acct = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert acct["contributions_ytd_cents"] == 432000
    assert acct["applicable_limit_cents"] == 432000
    assert acct["excess_contribution_cents"] == 0


def test_post_to_exact_limit_posture_open_step5(api):
    """PRD §3.4: "Finally posture is re-derived: it is `OPEN` exactly when the lifecycle
    is `ACTIVE` and `excess_contribution_cents` is zero, and `LOCKED` otherwise."

    Posting exactly the 432000 limit yields excess 0; with lifecycle ACTIVE posture
    derives to OPEN.

    Design: Difficulty/combinatorial_formula/contribution_accrual_pinned_eval_order
    """
    account, holder = setup_active_account(coverage_tier="SELF_ONLY",
                                           date_of_birth="1979-09-09",
                                           clock="2026-03-01T00:00:00Z")
    create_and_post_contribution(account["id"], "INDIVIDUAL", 432000)
    acct = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert acct["lifecycle_status"] == "ACTIVE"
    assert acct["excess_contribution_cents"] == 0
    assert acct["contribution_posture"] == "OPEN"


# ── post_contribution_posture_locked_only (Corner/validations) ───────────────

def test_post_blocked_when_posture_locked_by_excess(api):
    """PRD §3.4: "A post that drives `excess_contribution_cents` above zero therefore
    bubbles the account's `contribution_posture` to `LOCKED`, after which any further
    attempt to post a contribution is rejected with `ERR_POSTURE_LOCKED` until the
    excess is corrected."

    Design: Corner/validations/post_contribution_posture_locked_only
    """
    account, holder = setup_active_account(coverage_tier="SELF_ONLY",
                                           date_of_birth="1980-05-15",
                                           clock="2026-03-01T00:00:00Z")
    # 500000 overshoots the 432000 SELF_ONLY limit -> excess 68000, posture LOCKED.
    create_and_post_contribution(account["id"], "INDIVIDUAL", 500000)
    nxt = create_contribution(account["id"], "INDIVIDUAL", 10000)
    res = api.post_contribution(account["id"], nxt["id"], ADMIN_HDR)
    validate_error(res, ApiErrorId.ERR_POSTURE_LOCKED)
    acct = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert acct["contribution_posture"] == "LOCKED"
    assert acct["excess_contribution_cents"] == 68000


def test_post_blocked_posture_locked_keeps_contribution_pending(api):
    """PRD §3.4: "the account's `contribution_posture` is `OPEN` at post time (else
    `ERR_POSTURE_LOCKED`)."

    A post rejected for a LOCKED posture leaves the contribution PENDING.

    Design: Corner/validations/post_contribution_posture_locked_only
    """
    account, holder = setup_active_account(coverage_tier="SELF_ONLY",
                                           date_of_birth="1980-05-15",
                                           clock="2026-03-01T00:00:00Z")
    create_and_post_contribution(account["id"], "INDIVIDUAL", 500000)
    nxt = create_contribution(account["id"], "INDIVIDUAL", 10000)
    validate_error(api.post_contribution(account["id"], nxt["id"], ADMIN_HDR),
                   ApiErrorId.ERR_POSTURE_LOCKED)
    listed, _meta = validate_paginated(api.list_contributions(account["id"], ADMIN_HDR))
    target = next(c for c in listed if c["id"] == nxt["id"])
    assert target["status"] == "PENDING"


# ── catchup_contribution_ineligible_holder (Corner/validations) ──────────────

def test_post_catchup_for_ineligible_holder_rejected(api):
    """PRD §3.4: "If the contribution is `CATCH_UP`, the holder's
    `turns_55_or_older_in_plan_year` must be true (else `ERR_CATCHUP_INELIGIBLE`)."

    Holder born 1990 is age 36 in plan_year 2026 -> not catch-up eligible.

    Design: Corner/validations/catchup_contribution_ineligible_holder
    """
    account, holder = setup_active_account(coverage_tier="SELF_ONLY",
                                           date_of_birth="1990-01-01",
                                           clock="2026-03-01T00:00:00Z")
    contrib = create_contribution(account["id"], "INDIVIDUAL", 50000,
                                  contribution_kind="CATCH_UP")
    res = api.post_contribution(account["id"], contrib["id"], ADMIN_HDR)
    validate_error(res, ApiErrorId.ERR_CATCHUP_INELIGIBLE)
    listed, _meta = validate_paginated(api.list_contributions(account["id"], ADMIN_HDR))
    target = next(c for c in listed if c["id"] == contrib["id"])
    assert target["status"] == "PENDING"


# ── catchup_sub_limit_exceeded_eligible_holder (Corner/validations) ──────────

def test_catchup_sub_limit_exceeded_rejected(api):
    """PRD §3.4: "the sum of `amount_cents` over `POSTED` `CATCH_UP` contributions must
    not exceed the catch-up component (the catch-up annual figure of 100000 cents,
    prorated under the prorated variant). A post that would push the posted catch-up
    sum above that sub-limit is rejected with `ERR_CATCHUP_LIMIT_EXCEEDED`."

    Holder born 1965 (61 in 2026) is eligible. First CATCH_UP 60000 posts; a second
    CATCH_UP 50000 would push posted catch-up sum to 110000 > 100000.

    Design: Corner/validations/catchup_sub_limit_exceeded_eligible_holder
    """
    account, holder = setup_active_account(coverage_tier="FAMILY",
                                           date_of_birth="1965-03-15",
                                           clock="2026-03-01T00:00:00Z")
    create_and_post_contribution(account["id"], "INDIVIDUAL", 60000,
                                 contribution_kind="CATCH_UP")
    c2 = create_contribution(account["id"], "INDIVIDUAL", 50000,
                             contribution_kind="CATCH_UP")
    res = api.post_contribution(account["id"], c2["id"], ADMIN_HDR)
    validate_error(res, ApiErrorId.ERR_CATCHUP_LIMIT_EXCEEDED)
    acct = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert acct["contributions_ytd_cents"] == 60000


def test_catchup_sub_limit_exceeded_leaves_second_pending(api):
    """PRD §3.4: "A post that would push the posted catch-up sum above that sub-limit is
    rejected with `ERR_CATCHUP_LIMIT_EXCEEDED`."

    The over-limit second CATCH_UP stays PENDING (only the first posted).

    Design: Corner/validations/catchup_sub_limit_exceeded_eligible_holder
    """
    account, holder = setup_active_account(coverage_tier="FAMILY",
                                           date_of_birth="1965-03-15",
                                           clock="2026-03-01T00:00:00Z")
    create_and_post_contribution(account["id"], "INDIVIDUAL", 60000,
                                 contribution_kind="CATCH_UP")
    c2 = create_contribution(account["id"], "INDIVIDUAL", 50000,
                             contribution_kind="CATCH_UP")
    validate_error(api.post_contribution(account["id"], c2["id"], ADMIN_HDR),
                   ApiErrorId.ERR_CATCHUP_LIMIT_EXCEEDED)
    listed, _meta = validate_paginated(api.list_contributions(account["id"], ADMIN_HDR))
    target = next(c for c in listed if c["id"] == c2["id"])
    assert target["status"] == "PENDING"


# NOTE: The two payroll-disabled-beats-posture-locked tests were removed. They
# asserted that ERR_PAYROLL_DISABLED takes precedence over ERR_POSTURE_LOCKED
# when both conditions hold. PRD §3.4 states the post-time guards in the order
# "the account's `contribution_posture` is `OPEN` at post time (else
# `ERR_POSTURE_LOCKED`). If the contribution is on the `PAYROLL` channel, the
# named employer's `payroll_contributions_enabled` must be true (else
# `ERR_PAYROLL_DISABLED`)" — posture BEFORE payroll. PRD §2.9 binds these
# business-layer guards to "the relative orders described in their respective
# Section 3 narratives," and the only narrative order (§3.4) yields
# ERR_POSTURE_LOCKED first. A faithful PRD-only implementation therefore returns
# ERR_POSTURE_LOCKED, the opposite of the asserted outcome (ERROR PRECEDENCE
# collapse — STEP 1b unique-derivability failure), so the tests were deleted.


# ── immediate_consistency_balances_in_post_response (Corner/consistency_model) ─

def test_cash_credited_immediately_after_post(api):
    """PRD §3.4: "On a successful post the contribution moves from `PENDING` to
    `POSTED`, its `posted_at` is stamped from the logical clock, and the account's
    `cash_balance_cents` increases by the contribution's `amount_cents`."

    Design: Corner/consistency_model/immediate_consistency_balances_in_post_response
    """
    account, holder = setup_active_account(coverage_tier="SELF_ONLY")
    contrib = create_contribution(account["id"], "INDIVIDUAL", 70000)
    post_contribution(account["id"], contrib["id"])
    acct = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert acct["cash_balance_cents"] == 70000


# ── list_contributions_pagination_envelope (Corner/endpoints) ────────────────

def test_list_contributions_array_envelope_and_total(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.3: "The `meta` object of every list response carries the four pagination
    fields: `limit`, `offset`, `total_count`, and `has_more`."

    Two created contributions yield total_count == 2 with has_more false.

    Design: Corner/endpoints/list_contributions_pagination_envelope
    """
    account, holder = setup_active_account(coverage_tier="SELF_ONLY")
    create_contribution(account["id"], "INDIVIDUAL", 10000)
    create_contribution(account["id"], "INDIVIDUAL", 20000)
    data, meta = validate_paginated(api.list_contributions(account["id"], ADMIN_HDR))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(data) == 2
