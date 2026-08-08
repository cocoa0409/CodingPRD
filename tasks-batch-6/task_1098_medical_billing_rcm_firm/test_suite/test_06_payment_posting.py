"""Payment posting, PAID cascade to practice totals, reversal conservation,
remittance finalize/overallocation, negative amounts, and posting OCC.

Translates the transitive_cascade (posting) and compensating_invariant difficulty
instances plus the payment-posting corner and cross-cutting OCC instances.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_remittance_conservation, assert_claim_ledger_identity,
    make_account_manager_headers, make_payment_poster_headers,
    create_posting_payload,
)
from test_helpers import fixtures as fx

AM = make_account_manager_headers()
PP = make_payment_poster_headers()


def _accepted_claim_billed_15000(api, total_amount_cents=10000, remittance_ref="RA"):
    """Accepted claim (billed 15000, allowed 10000) + a remittance. Returns ctx with
    'remittance' added."""
    ctx = fx.setup_accepted_claim(
        api, prices={"99213": 10000},
        deductible_remaining_cents=0, coinsurance_pct=0.20, copay_cents=0,
        lines=[{"cpt_code": "99213", "units": 1, "charge_amount_cents": 15000}])
    ctx["remittance"] = fx.new_remittance(api, ctx["payer"]["id"],
                                          total_amount_cents=total_amount_cents,
                                          remittance_ref=remittance_ref)
    return ctx


# ---- Difficulty: transitive_cascade / posting cascades claim PAID then practice totals ----
def test_posting_drives_claim_to_paid(api):
    """PRD §3.6: "When a posting drives a claim's `outstanding_balance_cents` to zero or
    below while the claim is `ACCEPTED`, the claim moves automatically from `ACCEPTED`
    to `PAID`."

    Design: Difficulty/transitive_cascade/posting_cascades_claim_paid_then_practice_totals
    """
    ctx = _accepted_claim_billed_15000(api, total_amount_cents=10000, remittance_ref="RA-2")
    fx.new_posting(api, ctx["remittance"]["id"], ctx["claim"]["id"], ctx["claim_version"],
                   insurance_paid_cents=10000, patient_responsibility_cents=0, adjustment_cents=5000)
    claim = validate_success(api.get_claim(ctx["claim"]["id"], AM), 200)
    assert claim["status"] == "PAID", claim["status"]
    assert claim["insurance_paid_cents"] == 10000, claim["insurance_paid_cents"]
    assert claim["outstanding_balance_cents"] == 0, claim["outstanding_balance_cents"]


def test_paid_cascade_refreshes_practice_totals(api):
    """PRD §3.6: "On reaching `PAID`, the platform recomputes the owning practice's
    `collected_ytd_cents` and `ar_balance_cents` and accrues the practice's commission"
    PRD §2.9: "A practice's `ar_balance_cents` (the sum of `outstanding_balance_cents`
    across its non-terminal claims) and `collected_ytd_cents` (total insurance paid to
    its claims year to date) are likewise derived"

    Design: Difficulty/transitive_cascade/posting_cascades_claim_paid_then_practice_totals
    """
    ctx = _accepted_claim_billed_15000(api, total_amount_cents=10000, remittance_ref="RA-2")
    fx.new_posting(api, ctx["remittance"]["id"], ctx["claim"]["id"], ctx["claim_version"],
                   insurance_paid_cents=10000, patient_responsibility_cents=0, adjustment_cents=5000)
    practice = validate_success(api.get_practice(ctx["practice"]["id"], AM), 200)
    assert practice["collected_ytd_cents"] == 10000, practice["collected_ytd_cents"]
    assert practice["ar_balance_cents"] == 0, practice["ar_balance_cents"]


# ---- Difficulty: compensating_invariant / reversal restores remittance pool ----
def test_reversal_restores_remittance_allocation_pool(api):
    """PRD §3.6: "These two figures are recomputed on every posting create and every
    reversal, and the conservation identity that `total_amount_cents` equals
    `allocated_amount_cents` plus `unallocated_amount_cents` holds at all times — a
    reversal restores the unallocated pool exactly."

    Design: Difficulty/compensating_invariant/posting_reversal_restores_remittance_allocation_pool
    """
    ctx = _accepted_claim_billed_15000(api, total_amount_cents=10000, remittance_ref="RA-9")
    posting = fx.new_posting(api, ctx["remittance"]["id"], ctx["claim"]["id"],
                             ctx["claim_version"], insurance_paid_cents=6000)
    reversed_posting = validate_success(
        api.reverse_posting(posting["id"], {"reason": "posted to wrong claim"}, PP), 200)
    assert reversed_posting["status"] == "REVERSED", reversed_posting["status"]
    rem = validate_success(api.get_remittance(ctx["remittance"]["id"], AM), 200)
    assert rem["allocated_amount_cents"] == 0, rem["allocated_amount_cents"]
    assert rem["unallocated_amount_cents"] == 10000, rem["unallocated_amount_cents"]


def test_reversal_of_last_posting_reverses_remittance(api):
    """PRD §3.6: "When the last remaining posting under a remittance is reversed — that
    is, once all of the remittance's postings are `REVERSED` — the remittance itself
    moves from `POSTING` to `REVERSED`."

    Design: Difficulty/compensating_invariant/posting_reversal_restores_remittance_allocation_pool
    """
    ctx = _accepted_claim_billed_15000(api, total_amount_cents=10000, remittance_ref="RA-9")
    posting = fx.new_posting(api, ctx["remittance"]["id"], ctx["claim"]["id"],
                             ctx["claim_version"], insurance_paid_cents=6000)
    api.reverse_posting(posting["id"], {"reason": "posted to wrong claim"}, PP)
    rem = validate_success(api.get_remittance(ctx["remittance"]["id"], AM), 200)
    assert rem["status"] == "REVERSED", rem["status"]
    assert_remittance_conservation(rem)


# ---- Difficulty: compensating_invariant / reversal restores claim ledger identity ----
def test_reversal_restores_claim_ledger_values(api):
    """PRD §3.6: "Reversing sets the posting's `status` to `REVERSED`, recomputes both
    the claim ledger and the remittance allocation"
    PRD §3.6: "`insurance_paid_cents` is the sum of `insurance_paid_cents` across the
    claim's `POSTED` postings."

    Design: Difficulty/compensating_invariant/posting_reversal_restores_claim_ledger_identity
    """
    ctx = _accepted_claim_billed_15000(api, total_amount_cents=10000, remittance_ref="RA-10")
    posting = fx.new_posting(api, ctx["remittance"]["id"], ctx["claim"]["id"],
                             ctx["claim_version"], insurance_paid_cents=6000)
    api.reverse_posting(posting["id"], {"reason": "duplicate ERA line"}, PP)
    claim = validate_success(api.get_claim(ctx["claim"]["id"], AM), 200)
    assert claim["insurance_paid_cents"] == 0, claim["insurance_paid_cents"]
    assert claim["outstanding_balance_cents"] == 10000, claim["outstanding_balance_cents"]


def test_reversal_preserves_claim_ledger_identity(api):
    """PRD §3.6: "This closes the invariant that `billed_amount_cents` equals the sum of
    `contractual_adjustment_cents`, `insurance_paid_cents`, `patient_responsibility_cents`,
    `write_off_cents`, and `outstanding_balance_cents`."

    Design: Difficulty/compensating_invariant/posting_reversal_restores_claim_ledger_identity
    """
    ctx = _accepted_claim_billed_15000(api, total_amount_cents=10000, remittance_ref="RA-10")
    posting = fx.new_posting(api, ctx["remittance"]["id"], ctx["claim"]["id"],
                             ctx["claim_version"], insurance_paid_cents=6000)
    api.reverse_posting(posting["id"], {"reason": "duplicate ERA line"}, PP)
    claim = validate_success(api.get_claim(ctx["claim"]["id"], AM), 200)
    assert claim["billed_amount_cents"] == 15000, claim["billed_amount_cents"]
    assert claim["contractual_adjustment_cents"] == 5000, claim["contractual_adjustment_cents"]
    assert_claim_ledger_identity(claim)


# ---- Corner: validations / posting overallocation ----
def test_posting_overallocation_returns_overallocation(api):
    """PRD §3.6: "A posting is refused with `ERR_OVERALLOCATION` (HTTP 422) if it would
    push the remittance's allocated total above its `total_amount_cents`."

    Design: Corner/validations/posting_overallocation_returns_overallocation
    """
    ctx = _accepted_claim_billed_15000(api, total_amount_cents=5000, remittance_ref="RA-OA")
    resp = api.create_posting(
        ctx["remittance"]["id"],
        create_posting_payload(ctx["claim"]["id"], ctx["claim_version"], insurance_paid_cents=6000),
        PP)
    validate_error(resp, ApiErrorId.ERR_OVERALLOCATION.value)


# ---- Corner: validations / finalize unbalanced remittance ----
def test_finalize_unbalanced_remittance_returns_not_balanced(api):
    """PRD §3.6: "finalizing moves it from `POSTING` to `POSTED`, and is allowed only
    when its `allocated_amount_cents` equals its `total_amount_cents`; an attempt to
    finalize an unbalanced remittance is rejected with `ERR_REMITTANCE_NOT_BALANCED`
    (HTTP 422)."

    Design: Corner/validations/finalize_unbalanced_remittance_returns_not_balanced
    """
    ctx = _accepted_claim_billed_15000(api, total_amount_cents=10000, remittance_ref="RA-UB")
    fx.new_posting(api, ctx["remittance"]["id"], ctx["claim"]["id"], ctx["claim_version"],
                   insurance_paid_cents=6000)
    resp = api.finalize_remittance(ctx["remittance"]["id"], PP)
    validate_error(resp, ApiErrorId.ERR_REMITTANCE_NOT_BALANCED.value)
    rem = validate_success(api.get_remittance(ctx["remittance"]["id"], AM), 200)
    assert rem["status"] == "POSTING", rem["status"]


# ---- Corner: validations / negative insurance_paid ----
def test_negative_insurance_paid_returns_negative_amount(api):
    """PRD §3: "a monetary input supplied as a negative number is rejected with
    `ERR_NEGATIVE_AMOUNT` (HTTP 422)."

    Design: Corner/validations/negative_insurance_paid_returns_negative_amount
    """
    ctx = _accepted_claim_billed_15000(api, total_amount_cents=10000, remittance_ref="RA-NEG")
    resp = api.create_posting(
        ctx["remittance"]["id"],
        create_posting_payload(ctx["claim"]["id"], ctx["claim_version"], insurance_paid_cents=-100),
        PP)
    validate_error(resp, ApiErrorId.ERR_NEGATIVE_AMOUNT.value)


# ---- Corner: calculations / finalize a balanced remittance ----
def test_finalize_balanced_remittance_posts(api):
    """PRD §3.6: "A remittance is finalized once it is fully reconciled: finalizing moves
    it from `POSTING` to `POSTED`, and is allowed only when its `allocated_amount_cents`
    equals its `total_amount_cents`"

    Design: Corner/calculations/remittance_finalize_balanced_posts
    """
    ctx = _accepted_claim_billed_15000(api, total_amount_cents=10000, remittance_ref="RA-BAL")
    fx.new_posting(api, ctx["remittance"]["id"], ctx["claim"]["id"], ctx["claim_version"],
                   insurance_paid_cents=10000, patient_responsibility_cents=0, adjustment_cents=5000)
    rem = validate_success(api.finalize_remittance(ctx["remittance"]["id"], PP), 200)
    assert rem["status"] == "POSTED", rem["status"]
    assert rem["allocated_amount_cents"] == 10000, rem["allocated_amount_cents"]
    assert rem["unallocated_amount_cents"] == 0, rem["unallocated_amount_cents"]


# ---- Corner: cross_cutting / OCC stale claim version on posting ----
def test_posting_with_stale_claim_version_returns_stale_version(api):
    """PRD §2.6: "posting an ERA line against a claim requires the request to carry
    `expected_claim_version`, which must equal the target claim's current `version`.
    Because each successful posting advances the claim toward `PAID` and increments the
    claim's `version`, a stale `expected_claim_version` means another posting has already
    been applied and the poster's view of the claim balance is out of date; the create
    is rejected before it can double-count against a balance it never observed."

    Design: Corner/cross_cutting/occ_posting_stale_claim_version_returns_stale_version
    """
    ctx = _accepted_claim_billed_15000(api, total_amount_cents=20000, remittance_ref="RA-OCC")
    # First posting succeeds and advances the claim's version.
    fx.new_posting(api, ctx["remittance"]["id"], ctx["claim"]["id"], ctx["claim_version"],
                   insurance_paid_cents=3000)
    # Second posting reuses the now-stale expected_claim_version.
    resp = api.create_posting(
        ctx["remittance"]["id"],
        create_posting_payload(ctx["claim"]["id"], ctx["claim_version"], insurance_paid_cents=3000),
        PP)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
