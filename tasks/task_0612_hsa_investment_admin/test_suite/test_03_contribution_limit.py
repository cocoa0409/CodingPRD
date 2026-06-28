"""HDHP coverage and the contribution limit: the last-month-rule limit, coverage
overlap, and the supersede/correction cascades that move the limit and posture.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
)
from test_helpers.fixtures import (
    ADMIN, set_clock, create_accountholder, open_account, attest_coverage,
    verify_account, setup_active_account, create_and_post_contribution,
    create_contribution, post_contribution, account_version, create_correction,
)
from test_helpers.api_client import api_client

ADMIN_HDR = ADMIN


# ── limit_last_month_rule_vs_prorated_on_account (Difficulty/dual_variant_calc) ─
# NOTE on coverage: the LAST_MONTH_RULE branch (December FAMILY coverage -> full annual
# 862500) is verbatim and uniquely derivable from PRD §3.3. The PRORATED exact value
# 503125 is NOT uniquely derivable from PRD prose (PRD §3.3 says each month's tier amount
# is "the corresponding annual figure divided by twelve, kept as exact cents" and the base
# is "the sum ... divided by twelve and floored", which a faithful PRD-only reader computes
# differently), so the 503125 assertion is omitted per the PRD-first Core rule. Both tests
# below assert the cleanly derivable LAST_MONTH_RULE limit.

def test_last_month_rule_family_december_full_annual(api):
    """PRD §3.3: "Under `LAST_MONTH_RULE` (the default), the base limit is the full
    undivided annual figure for the coverage in force in December: it is the family
    annual figure of 862500 cents if month 12 is covered by an attested family period,
    otherwise the self-only annual figure of 432000 cents if month 12 is covered by any
    attested period, otherwise zero."

    FAMILY coverage spanning months 6..12 (December covered by FAMILY) -> 862500 under
    the default last-month rule.

    Design: Difficulty/dual_variant_calc/limit_last_month_rule_vs_prorated_on_account
    """
    account, holder = setup_active_account(coverage_tier="FAMILY",
                                           effective_month=6, end_month=12,
                                           date_of_birth="1985-06-01",
                                           clock="2026-01-01T00:00:00Z")
    acct = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert acct["applicable_limit_cents"] == 862500


def test_last_month_rule_default_variant_no_catchup(api):
    """PRD §3.3: "The account computes its limit under one of two variants, and the
    default for every account is the **last-month rule**."
    PRD §3.3: "it is the family annual figure of 862500 cents if month 12 is covered by
    an attested family period".

    A FAMILY-in-December account with a non-eligible holder (DOB 1985) gets exactly the
    862500 base with no catch-up component.

    Design: Difficulty/dual_variant_calc/limit_last_month_rule_vs_prorated_on_account
    """
    account, holder = setup_active_account(coverage_tier="FAMILY",
                                           effective_month=6, end_month=12,
                                           date_of_birth="1985-06-01",
                                           clock="2026-01-01T00:00:00Z")
    acct = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    # Holder born 1985 turns 41 in 2026 -> not catch-up eligible -> base only.
    assert acct["applicable_limit_cents"] == 862500


# ── coverage_period_closed_closed_overlap (Difficulty/resource_temporal_overlap) ─

def test_coverage_overlap_closed_closed_shared_month_rejected(api):
    """PRD §3.3: "A new period is rejected with `ERR_COVERAGE_OVERLAP` (HTTP 409) when
    the months fall outside 1 through 12, when `effective_month` is greater than
    `end_month`, or when the closed-closed interval overlaps an existing `ATTESTED`
    period on the account. Two closed-closed intervals overlap exactly when the first's
    effective month is at most the second's end month and the second's effective month
    is at most the first's end month".

    Existing ATTESTED months 1..6; new months 6..9 share month 6 -> overlap.

    Design: Difficulty/resource_temporal_overlap/coverage_period_closed_closed_overlap
    """
    set_clock("2026-03-01T00:00:00Z")
    holder = create_accountholder(date_of_birth="1975-05-25")
    account = open_account(holder["id"], plan_year=2026)
    attest_coverage(account["id"], "SELF_ONLY", 1, 6)
    res = api.create_coverage_period(
        account["id"], {"coverage_tier": "FAMILY", "effective_month": 6, "end_month": 9},
        ADMIN_HDR)
    validate_error(res, ApiErrorId.ERR_COVERAGE_OVERLAP)


def test_coverage_adjacent_period_allowed(api):
    """PRD §3.3: "adjacency, where one period ends at a month and the next begins at the
    following month, is allowed."

    Existing ATTESTED months 1..6; a new adjacent period months 7..9 (boundary 6/7)
    shares no month and is accepted (201).

    Design: Difficulty/resource_temporal_overlap/coverage_period_closed_closed_overlap
    """
    set_clock("2026-03-01T00:00:00Z")
    holder = create_accountholder(date_of_birth="1975-05-25")
    account = open_account(holder["id"], plan_year=2026)
    attest_coverage(account["id"], "SELF_ONLY", 1, 6)
    res = api.create_coverage_period(
        account["id"], {"coverage_tier": "FAMILY", "effective_month": 7, "end_month": 9},
        ADMIN_HDR)
    period = validate_success(res, 201)
    assert period["status"] == "ATTESTED"


# ── coverage_supersede_depth2_cascade (Difficulty/transitive_cascade) ────────

def test_supersede_coverage_drops_limit_and_locks_posture(api):
    """PRD §3.3: "superseding moves it to `SUPERSEDED`, after which it is excluded from
    all limit math, and triggers a recomputation of the account's `applicable_limit_cents`,
    `excess_contribution_cents`, and posture, which may newly lock the account."
    PRD §3.3: "otherwise zero" (when month 12 is not covered by any attested period).

    FAMILY full-year (limit 862500) with 600000 posted (excess 0, OPEN). Superseding the
    only coverage drops the limit to 0, making 600000 fully excess and locking posture.

    Design: Difficulty/transitive_cascade/coverage_supersede_depth2_cascade
    """
    set_clock("2026-03-01T00:00:00Z")
    holder = create_accountholder(date_of_birth="1981-01-01")
    account = open_account(holder["id"], plan_year=2026)
    cp = attest_coverage(account["id"], "FAMILY", 1, 12)
    verify_account(account["id"], holder["id"], account["verification_token"])
    create_and_post_contribution(account["id"], "INDIVIDUAL", 600000)
    before = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert before["excess_contribution_cents"] == 0
    assert before["contribution_posture"] == "OPEN"
    superseded = validate_success(
        api.supersede_coverage_period(account["id"], cp["id"], ADMIN_HDR), 200)
    assert superseded["status"] == "SUPERSEDED"
    after = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert after["applicable_limit_cents"] == 0
    assert after["excess_contribution_cents"] == 600000
    assert after["contribution_posture"] == "LOCKED"


def test_supersede_coverage_limit_recomputes_to_zero(api):
    """PRD §3.3: "The limit itself, `applicable_limit_cents`, is derived from the set of
    `ATTESTED` coverage periods only — `SUPERSEDED` periods never count".

    After the only coverage period is superseded, no ATTESTED coverage remains and the
    last-month-rule base is zero.

    Design: Difficulty/transitive_cascade/coverage_supersede_depth2_cascade
    """
    set_clock("2026-03-01T00:00:00Z")
    holder = create_accountholder(date_of_birth="1981-01-01")
    account = open_account(holder["id"], plan_year=2026)
    cp = attest_coverage(account["id"], "FAMILY", 1, 12)
    verify_account(account["id"], holder["id"], account["verification_token"])
    create_and_post_contribution(account["id"], "INDIVIDUAL", 600000)
    validate_success(api.supersede_coverage_period(account["id"], cp["id"], ADMIN_HDR), 200)
    after = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert after["applicable_limit_cents"] == 0


# ── correction_execute_depth3_cascade (Difficulty/transitive_cascade) ────────

def _setup_account_with_three_contributions_and_correction(api):
    """FAMILY full-year (limit 862500). Three POSTED contributions 400000 (3-01),
    400000 (3-02), 200000 (3-03) -> ytd 1000000, excess 137500, posture LOCKED.
    Returns (account, holder, [c1,c2,c3], correction)."""
    set_clock("2026-03-01T00:00:00Z")
    holder = create_accountholder(date_of_birth="1978-08-08")
    account = open_account(holder["id"], plan_year=2026)
    attest_coverage(account["id"], "FAMILY", 1, 12)
    verify_account(account["id"], holder["id"], account["verification_token"])
    c1 = create_and_post_contribution(account["id"], "INDIVIDUAL", 400000)
    set_clock("2026-03-02T00:00:00Z")
    c2 = create_and_post_contribution(account["id"], "INDIVIDUAL", 400000)
    set_clock("2026-03-03T00:00:00Z")
    c3 = create_and_post_contribution(account["id"], "INDIVIDUAL", 200000)
    v = account_version(account["id"])
    corr = create_correction(account["id"], 137500, v)
    return account, holder, [c1, c2, c3], corr


def test_correction_execute_cascade_reverses_latest_and_unlocks(api):
    """PRD §3.9: "The platform orders the `POSTED` contributions by `posted_at`
    descending, breaking ties by `created_at` descending — latest first — and walks that
    order, marking each contribution `POSTED → REVERSED` and accumulating the reversed
    sum, until the accumulated reversed sum is at least the corrected amount."
    PRD §3.9: "After the walk, `excess_contribution_cents` is recomputed and must be
    zero, since the reversed sum is at least the exact excess, and the account's
    `contribution_posture` bubbles back up to `OPEN`."

    Design: Difficulty/transitive_cascade/correction_execute_depth3_cascade
    """
    account, holder, contribs, corr = \
        _setup_account_with_three_contributions_and_correction(api)
    executed = validate_success(
        api.execute_correction(account["id"], corr["id"], ADMIN_HDR), 200)
    assert executed["status"] == "COMPLETED"
    assert executed["corrected_amount_cents"] == 137500
    after = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert after["contributions_ytd_cents"] == 800000
    assert after["cash_balance_cents"] == 800000
    assert after["excess_contribution_cents"] == 0
    assert after["contribution_posture"] == "OPEN"


def test_correction_execute_reverses_only_latest_contribution(api):
    """PRD §3.9: "Contributions are atomic: the last contribution touched is reversed in
    full with no partial reversal, so the reversed sum may exceed the corrected amount."

    The latest-posted contribution (c3 = 200000) is reversed in full to absorb the
    137500 excess; c1 and c2 remain POSTED.

    Design: Difficulty/transitive_cascade/correction_execute_depth3_cascade
    """
    account, holder, contribs, corr = \
        _setup_account_with_three_contributions_and_correction(api)
    c1, c2, c3 = contribs
    validate_success(api.execute_correction(account["id"], corr["id"], ADMIN_HDR), 200)
    listed, _meta = validate_paginated(api.list_contributions(account["id"], ADMIN_HDR))
    by_id = {c["id"]: c for c in listed}
    assert by_id[c3["id"]]["status"] == "REVERSED"
    assert by_id[c1["id"]]["status"] == "POSTED"
    assert by_id[c2["id"]]["status"] == "POSTED"


# ── excess_correction_amount_mismatch (Corner/calculations) ──────────────────

def test_correction_execute_stale_requested_amount_rejected(api):
    """PRD §3.9: "requires that the correction's `requested_amount_cents` equals the
    current `excess_contribution_cents` at execution (else
    `ERR_CORRECTION_AMOUNT_MISMATCH`)."

    A correction created for 137500 is made stale by superseding the only coverage
    (limit -> 0, excess -> 1000000); executing it mismatches and is rejected.

    Design: Corner/calculations/excess_correction_amount_mismatch
    """
    set_clock("2026-03-01T00:00:00Z")
    holder = create_accountholder(date_of_birth="1978-04-08")
    account = open_account(holder["id"], plan_year=2026)
    cp = attest_coverage(account["id"], "FAMILY", 1, 12)
    verify_account(account["id"], holder["id"], account["verification_token"])
    create_and_post_contribution(account["id"], "INDIVIDUAL", 400000)
    create_and_post_contribution(account["id"], "INDIVIDUAL", 400000)
    create_and_post_contribution(account["id"], "INDIVIDUAL", 200000)
    v = account_version(account["id"])
    corr = create_correction(account["id"], 137500, v)
    validate_success(api.supersede_coverage_period(account["id"], cp["id"], ADMIN_HDR), 200)
    res = api.execute_correction(account["id"], corr["id"], ADMIN_HDR)
    validate_error(res, ApiErrorId.ERR_CORRECTION_AMOUNT_MISMATCH)
    listed, _meta = validate_paginated(api.list_corrections(account["id"], ADMIN_HDR))
    target = next(c for c in listed if c["id"] == corr["id"])
    assert target["status"] == "REQUESTED"
