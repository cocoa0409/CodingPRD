"""Filing and adjudicating claims: indemnity, revision loop, cascades, conservation.

Queue A:
  dual_variant_calc / claim_indemnity_deposit_sublimit_binds
  combinatorial_formula / claim_indemnity_three_way_min_line_limit_binds
  non_linear_state_machine / claim_revision_cycle_increments_revision_count
  transitive_cascade / claim_approve_exhausts_only_coverage_bubbles_policy_claimed_out
  boundary_precision_check / resubmit_blocked_when_revision_count_at_cap
  cross_entity_state_dependency / vendor_failure_claim_approval_requires_vendor_defaulted
  compensating_invariant / coverage_limit_conserved_remaining_plus_consumed_plus_payout
Queue B:
  state_machines / approve_claim_in_denied_terminal_state_rejected
  state_machines / resubmit_without_new_documentation_rejected
  validations / approve_claim_without_documentation_rejected
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    make_policyholder_headers, TEST_USERS,
)
from test_helpers import fixtures as FX
from test_helpers.assertions import ledger_sum_by_kind

_admin = TEST_USERS["admin_headers"]
_uw = TEST_USERS["underwriter_headers"]
_adj = TEST_USERS["adjuster_headers"]
_ph = make_policyholder_headers("ph-1")


# ─── Indemnity calculation ────────────────────────────────────────────────
def test_claim_indemnity_deposit_sublimit_binds(api):
    """PRD §3.7: "when the claim type is `VENDOR_FAILURE` or `CANCELLATION`, the cap is the
    product's `coverage_limit_cents` multiplied by its `deposit_sublimit_pct`, taken down
    to the whole cent below".
    PRD §3.7: "Third it takes the minimum of the `claimed_amount_cents`, the remaining line
    limit, and the sublimit cap, and records that as the claim's `approved_amount_cents`."

    Design: Difficulty/dual_variant_calc/claim_indemnity_deposit_sublimit_binds
    """
    # CANCELLATION coverage: limit 5_000_000, deposit_sublimit_pct 0.5; claim 3_000_000.
    ctx, claim = FX.setup_submitted_claim(
        claim_type="CANCELLATION", claimed_amount_cents=3000000,
        doc_overrides={"doc_type": "INVOICE", "file_uri": "s3://docs/inv1.pdf"})
    pid = ctx["policy"]["id"]
    approved = validate_success(api.approve_claim(pid, claim["id"], _adj), 200)
    # min(3_000_000, remaining 5_000_000, sublimit floor(5_000_000*0.5)=2_500_000) = 2_500_000
    assert approved["approved_amount_cents"] == 2500000
    assert approved["status"] == "APPROVED"
    cov = validate_success(api.get_coverage(pid, ctx["coverage"]["id"], _uw), 200)
    assert cov["consumed_limit_cents"] == 2500000
    assert cov["status"] == "ACTIVE"


def test_claim_indemnity_deposit_sublimit_bumps_consumed_limit(api):
    """PRD §3.7: "The approval then adds the `approved_amount_cents` to the coverage line's
    `consumed_limit_cents`".
    PRD §3.7: "when the claim type is `VENDOR_FAILURE` or `CANCELLATION`, the cap is the
    product's `coverage_limit_cents` multiplied by its `deposit_sublimit_pct`, taken down to
    the whole cent below".

    Design: Difficulty/dual_variant_calc/claim_indemnity_deposit_sublimit_binds
    """
    ctx, claim = FX.setup_submitted_claim(
        claim_type="CANCELLATION", claimed_amount_cents=3000000,
        doc_overrides={"doc_type": "INVOICE", "file_uri": "s3://docs/inv2.pdf"})
    pid = ctx["policy"]["id"]
    cov_before = validate_success(api.get_coverage(pid, ctx["coverage"]["id"], _uw), 200)
    assert cov_before["consumed_limit_cents"] == 0
    validate_success(api.approve_claim(pid, claim["id"], _adj), 200)
    cov_after = validate_success(api.get_coverage(pid, ctx["coverage"]["id"], _uw), 200)
    # sublimit floor(5_000_000 * 0.5) = 2_500_000 binds below claimed 3_000_000.
    assert cov_after["consumed_limit_cents"] == 2500000
    assert cov_after["status"] == "ACTIVE"  # 2_500_000 < limit 5_000_000


def test_claim_indemnity_three_way_min_line_limit_binds(api):
    """PRD §3.7: "First the system computes the **remaining line limit** as the product's
    `coverage_limit_cents` minus the coverage line's current `consumed_limit_cents`."
    PRD §3.7: "for any other claim type, the cap is simply the product's full
    `coverage_limit_cents` with no deposit sublimit applied."
    PRD §3.7: "if that running total reaches or exceeds the product's `coverage_limit_cents`,
    the coverage line flips from `ACTIVE` to `EXHAUSTED`."

    Design: Difficulty/combinatorial_formula/claim_indemnity_three_way_min_line_limit_binds
    """
    # LIABILITY coverage: limit 2_000_000, no deposit sublimit. PROPERTY claim 2_500_000.
    ctx = FX.setup_in_force_policy_liability_only()
    pid = ctx["policy"]["id"]
    claim = FX.file_claim(pid, ctx["coverage"]["id"], "PROPERTY", 2500000)
    FX.attach_document(pid, claim["id"], doc_type="PHOTO", file_uri="s3://docs/photo1.jpg")
    approved = validate_success(api.approve_claim(pid, claim["id"], _adj), 200)
    # min(2_500_000, remaining 2_000_000, cap 2_000_000) = 2_000_000
    assert approved["approved_amount_cents"] == 2000000
    cov = validate_success(api.get_coverage(pid, ctx["coverage"]["id"], _uw), 200)
    assert cov["consumed_limit_cents"] == 2000000
    assert cov["status"] == "EXHAUSTED"


def test_claim_indemnity_line_limit_exhausts_coverage(api):
    """PRD §3.7: "for any other claim type, the cap is simply the product's full
    `coverage_limit_cents` with no deposit sublimit applied."
    PRD §3.7: "if that running total reaches or exceeds the product's `coverage_limit_cents`,
    the coverage line flips from `ACTIVE` to `EXHAUSTED`."

    Design: Difficulty/combinatorial_formula/claim_indemnity_three_way_min_line_limit_binds
    """
    ctx = FX.setup_in_force_policy_liability_only()  # LIABILITY limit 2_000_000, no sublimit
    pid = ctx["policy"]["id"]
    # Claim above the line limit; remaining_line (2_000_000) binds the min.
    claim = FX.file_claim(pid, ctx["coverage"]["id"], "PROPERTY", 9999999)
    FX.attach_document(pid, claim["id"], doc_type="PHOTO", file_uri="s3://docs/photo2.jpg")
    approved = validate_success(api.approve_claim(pid, claim["id"], _adj), 200)
    assert approved["approved_amount_cents"] == 2000000
    cov = validate_success(api.get_coverage(pid, ctx["coverage"]["id"], _uw), 200)
    assert cov["status"] == "EXHAUSTED"


# ─── Cyclic revision loop ─────────────────────────────────────────────────
def test_claim_revision_cycle_increments_revision_count(api):
    """PRD §3.7: "A `ClaimsAdjuster` may request more information on a submitted claim,
    advancing it from `SUBMITTED` to `INFO_REQUESTED`".
    PRD §3.7: "When a resubmission is allowed, the claim's `revision_count` is increased by
    one and its `version` is incremented."

    Design: Difficulty/non_linear_state_machine/claim_revision_cycle_increments_revision_count
    """
    ctx, claim = FX.setup_submitted_claim(claimed_amount_cents=1000000)
    pid = ctx["policy"]["id"]
    cid = claim["id"]
    validate_success(api.request_info_claim(pid, cid, _adj), 200)
    FX.attach_document(pid, cid, doc_type="RECEIPT", file_uri="s3://docs/rec1.pdf")
    resubmitted = validate_success(api.resubmit_claim(pid, cid, _ph), 200)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_count"] == 1


def test_request_info_moves_claim_to_info_requested(api):
    """PRD §3.7: "A `ClaimsAdjuster` may request more information on a submitted claim,
    advancing it from `SUBMITTED` to `INFO_REQUESTED`; this requires the claim to be
    `SUBMITTED`, otherwise `ERR_CLAIM_NOT_SUBMITTED` is returned".

    Design: Difficulty/non_linear_state_machine/claim_revision_cycle_increments_revision_count
    """
    ctx, claim = FX.setup_submitted_claim(claimed_amount_cents=1000000)
    pid = ctx["policy"]["id"]
    info = validate_success(api.request_info_claim(pid, claim["id"], _adj), 200)
    assert info["status"] == "INFO_REQUESTED"
    assert info["revision_count"] == 0


def test_resubmit_blocked_when_revision_count_at_cap(api):
    """PRD §3.7: "The revision loop is bounded: a claim's `revision_count` may legally climb
    to a maximum of 3, and resubmission is barred once the count has already reached 3 —
    the attempt that would push it past the cap is rejected with
    `ERR_REVISION_CAP_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/resubmit_blocked_when_revision_count_at_cap
    """
    ctx, cid = FX.claim_at_revision_cap()
    pid = ctx["policy"]["id"]
    res = api.resubmit_claim(pid, cid, _ph)
    validate_error(res, "ERR_REVISION_CAP_EXCEEDED", 422)
    refreshed = validate_success(api.get_claim(pid, cid, _uw), 200)
    assert refreshed["revision_count"] == 3


def test_resubmit_legal_at_third_revision(api):
    """PRD §3.7: "a claim's `revision_count` may legally climb to a maximum of 3, and
    resubmission is barred once the count has already reached 3 — the attempt that would
    push it past the cap is rejected with `ERR_REVISION_CAP_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/resubmit_blocked_when_revision_count_at_cap
    """
    # Build a claim cycled to revision_count==2, in INFO_REQUESTED with a fresh doc; the
    # third resubmit is the last legal one (pushes count to 3, not past the cap).
    ctx = FX.setup_in_force_policy_canc_only()
    pid = ctx["policy"]["id"]
    claim = FX.file_claim(pid, ctx["coverage"]["id"], "CANCELLATION", 1000000)
    cid = claim["id"]
    FX.attach_document(pid, cid, doc_type="INVOICE", file_uri="s3://docs/d0.pdf")
    for i in range(1, 3):  # two full cycles -> revision_count == 2
        validate_success(api.request_info_claim(pid, cid, _adj), 200)
        FX.attach_document(pid, cid, doc_type="RECEIPT", file_uri=f"s3://docs/d{i}.pdf")
        validate_success(api.resubmit_claim(pid, cid, _ph), 200)
    validate_success(api.request_info_claim(pid, cid, _adj), 200)
    FX.attach_document(pid, cid, doc_type="RECEIPT", file_uri="s3://docs/d3.pdf")
    resubmitted = validate_success(api.resubmit_claim(pid, cid, _ph), 200)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_count"] == 3


# ─── Cascades and conservation ────────────────────────────────────────────
def test_claim_approve_exhausts_only_coverage_bubbles_policy_claimed_out(api):
    """PRD §3.7: "The approval then adds the `approved_amount_cents` to the coverage line's
    `consumed_limit_cents`; if that running total reaches or exceeds the product's
    `coverage_limit_cents`, the coverage line flips from `ACTIVE` to `EXHAUSTED`."
    PRD §3.7: "if every coverage line on the policy is now in `EXHAUSTED` or `VOIDED` and at
    least one is `EXHAUSTED`, the policy's `lifecycle_status` advances automatically from
    `IN_FORCE` to `CLAIMED_OUT`".

    Design: Difficulty/transitive_cascade/claim_approve_exhausts_only_coverage_bubbles_policy_claimed_out
    """
    ctx = FX.setup_in_force_policy_liability_only()  # single LIABILITY coverage, limit 2_000_000
    pid = ctx["policy"]["id"]
    claim = FX.file_claim(pid, ctx["coverage"]["id"], "PROPERTY", 2000000)
    FX.attach_document(pid, claim["id"], doc_type="PHOTO", file_uri="s3://docs/photo1.jpg")
    validate_success(api.approve_claim(pid, claim["id"], _adj), 200)
    cov = validate_success(api.get_coverage(pid, ctx["coverage"]["id"], _uw), 200)
    assert cov["consumed_limit_cents"] == 2000000
    assert cov["status"] == "EXHAUSTED"
    policy = validate_success(api.get_policy(pid, _uw), 200)
    assert policy["lifecycle_status"] == "CLAIMED_OUT"


def test_claim_approve_consumes_full_limit_before_bubble_up(api):
    """PRD §3.7: "The approval then adds the `approved_amount_cents` to the coverage line's
    `consumed_limit_cents`; if that running total reaches or exceeds the product's
    `coverage_limit_cents`, the coverage line flips from `ACTIVE` to `EXHAUSTED`."
    PRD §3.7: "the policy's `lifecycle_status` advances automatically from `IN_FORCE` to
    `CLAIMED_OUT`".

    Design: Difficulty/transitive_cascade/claim_approve_exhausts_only_coverage_bubbles_policy_claimed_out
    """
    ctx = FX.setup_in_force_policy_liability_only()
    pid = ctx["policy"]["id"]
    before = validate_success(api.get_policy(pid, _uw), 200)
    assert before["lifecycle_status"] == "IN_FORCE"
    claim = FX.file_claim(pid, ctx["coverage"]["id"], "PROPERTY", 2000000)
    FX.attach_document(pid, claim["id"], doc_type="PHOTO", file_uri="s3://docs/p3.jpg")
    validate_success(api.approve_claim(pid, claim["id"], _adj), 200)
    cov = validate_success(api.get_coverage(pid, ctx["coverage"]["id"], _uw), 200)
    assert cov["status"] == "EXHAUSTED"
    policy = validate_success(api.get_policy(pid, _uw), 200)
    assert policy["lifecycle_status"] == "CLAIMED_OUT"
    assert policy["version"] > before["version"]


def test_coverage_limit_conserved_remaining_plus_consumed_plus_payout(api):
    """PRD §3.7: "Paying the claim appends an `INDEMNITY_PAYOUT` ledger entry whose
    `amount_cents` is the negative of the claim's `approved_amount_cents`".
    PRD §3.7: "the coverage line flips from `ACTIVE` to `EXHAUSTED`."

    Design: Difficulty/compensating_invariant/coverage_limit_conserved_remaining_plus_consumed_plus_payout
    """
    ctx = FX.setup_in_force_policy_liability_only()  # limit 2_000_000
    pid = ctx["policy"]["id"]
    claim = FX.file_claim(pid, ctx["coverage"]["id"], "PROPERTY", 2000000)
    FX.attach_document(pid, claim["id"], doc_type="PHOTO", file_uri="s3://docs/p.jpg")
    validate_success(api.approve_claim(pid, claim["id"], _adj), 200)
    paid = validate_success(api.pay_claim(pid, claim["id"], _adj), 200)
    assert paid["status"] == "PAID"
    cov = validate_success(api.get_coverage(pid, ctx["coverage"]["id"], _uw), 200)
    assert cov["consumed_limit_cents"] == 2000000
    assert cov["status"] == "EXHAUSTED"
    data, _ = validate_paginated(api.list_ledger(pid, _uw))
    assert ledger_sum_by_kind(data, "INDEMNITY_PAYOUT") == -2000000


def test_coverage_capacity_conserved_consumed_equals_limit_after_full_draw(api):
    """PRD §3.7: "First the system computes the **remaining line limit** as the product's
    `coverage_limit_cents` minus the coverage line's current `consumed_limit_cents`."
    PRD §3.7: "Paying the claim appends an `INDEMNITY_PAYOUT` ledger entry whose
    `amount_cents` is the negative of the claim's `approved_amount_cents`".

    Design: Difficulty/compensating_invariant/coverage_limit_conserved_remaining_plus_consumed_plus_payout
    """
    ctx = FX.setup_in_force_policy_liability_only()  # limit 2_000_000
    pid = ctx["policy"]["id"]
    claim = FX.file_claim(pid, ctx["coverage"]["id"], "PROPERTY", 2000000)
    FX.attach_document(pid, claim["id"], doc_type="PHOTO", file_uri="s3://docs/p4.jpg")
    approved = validate_success(api.approve_claim(pid, claim["id"], _adj), 200)
    validate_success(api.pay_claim(pid, claim["id"], _adj), 200)
    cov = validate_success(api.get_coverage(pid, ctx["coverage"]["id"], _uw), 200)
    limit = 2000000
    # consumed + remaining == limit, with remaining == 0 here.
    assert cov["consumed_limit_cents"] == limit
    remaining = limit - cov["consumed_limit_cents"]
    assert remaining == 0
    data, _ = validate_paginated(api.list_ledger(pid, _uw))
    assert ledger_sum_by_kind(data, "INDEMNITY_PAYOUT") == -approved["approved_amount_cents"]


# ─── Cross-entity gate: vendor default ────────────────────────────────────
def test_vendor_failure_claim_approval_requires_vendor_defaulted(api):
    """PRD §3.7: "For a `VENDOR_FAILURE` claim, the referenced vendor must be `DEFAULTED`
    at approval time, or `ERR_VENDOR_NOT_DEFAULTED` is returned."

    Design: Difficulty/cross_entity_state_dependency/vendor_failure_claim_approval_requires_vendor_defaulted
    """
    canc = FX.create_cancellation_product()
    venue = FX.create_venue()
    caterer = FX.create_defaulted_caterer()  # SOLVENT -> FLAGGED -> DEFAULTED
    policy = FX.create_quoted_policy()
    FX.add_event_profile(policy["id"], venue["id"], expected_attendance=150)
    coverage = FX.add_coverage(policy["id"], canc["id"], protected_vendor_id=caterer["id"])
    FX.bind_policy(policy["id"])
    FX.pay_policy(policy["id"], 65000)
    FX.activate_coverage(policy["id"])
    claim = FX.file_claim(policy["id"], coverage["id"], "VENDOR_FAILURE", 500000,
                          vendor_id=caterer["id"])
    FX.attach_document(policy["id"], claim["id"], doc_type="VENDOR_CONTRACT",
                       file_uri="s3://docs/contract.pdf", subject_kind="VENDOR",
                       subject_ref=caterer["id"])
    approved = validate_success(api.approve_claim(policy["id"], claim["id"], _adj), 200)
    assert approved["status"] == "APPROVED"
    # min(claimed 500000, remaining 5_000_000, sublimit floor(5_000_000*0.5)=2_500_000)=500000
    assert approved["approved_amount_cents"] == 500000


def test_vendor_failure_claim_approval_blocked_while_solvent(api):
    """PRD §3.7: "For a `VENDOR_FAILURE` claim, the referenced vendor must be `DEFAULTED`
    at approval time, or `ERR_VENDOR_NOT_DEFAULTED` is returned."

    Design: Difficulty/cross_entity_state_dependency/vendor_failure_claim_approval_requires_vendor_defaulted
    """
    canc = FX.create_cancellation_product()
    venue = FX.create_venue()
    caterer = FX.create_caterer()  # stays SOLVENT
    policy = FX.create_quoted_policy()
    FX.add_event_profile(policy["id"], venue["id"], expected_attendance=150)
    coverage = FX.add_coverage(policy["id"], canc["id"], protected_vendor_id=caterer["id"])
    FX.bind_policy(policy["id"])
    FX.pay_policy(policy["id"], 65000)
    FX.activate_coverage(policy["id"])
    claim = FX.file_claim(policy["id"], coverage["id"], "VENDOR_FAILURE", 500000,
                          vendor_id=caterer["id"])
    FX.attach_document(policy["id"], claim["id"], doc_type="VENDOR_CONTRACT",
                       file_uri="s3://docs/contract.pdf")
    res = api.approve_claim(policy["id"], claim["id"], _adj)
    validate_error(res, "ERR_VENDOR_NOT_DEFAULTED", 422)


# ─── Claim adjudication corner instances ──────────────────────────────────
def test_approve_claim_in_denied_terminal_state_rejected(api):
    """PRD §3.7: "The claim must be `SUBMITTED`, or `ERR_CLAIM_NOT_SUBMITTED` is returned."

    Design: Corner/state_machines/approve_claim_in_denied_terminal_state_rejected
    """
    ctx, claim = FX.setup_submitted_claim(claimed_amount_cents=1000000)
    pid = ctx["policy"]["id"]
    validate_success(api.deny_claim(pid, claim["id"], _adj), 200)
    res = api.approve_claim(pid, claim["id"], _adj)
    validate_error(res, "ERR_CLAIM_NOT_SUBMITTED", 409)
    refreshed = validate_success(api.get_claim(pid, claim["id"], _uw), 200)
    assert refreshed["status"] == "DENIED"


def test_resubmit_without_new_documentation_rejected(api):
    """PRD §3.7: "it requires that at least one new `ClaimDocument` has been added since the
    claim last entered `INFO_REQUESTED`, otherwise `ERR_NO_NEW_DOCUMENTATION` is returned."

    Design: Corner/state_machines/resubmit_without_new_documentation_rejected
    """
    ctx, claim = FX.setup_submitted_claim(claimed_amount_cents=1000000)
    pid = ctx["policy"]["id"]
    cid = claim["id"]
    validate_success(api.request_info_claim(pid, cid, _adj), 200)
    res = api.resubmit_claim(pid, cid, _ph)  # no new document added
    validate_error(res, "ERR_NO_NEW_DOCUMENTATION", 422)
    refreshed = validate_success(api.get_claim(pid, cid, _uw), 200)
    assert refreshed["status"] == "INFO_REQUESTED"


def test_approve_claim_without_documentation_rejected(api):
    """PRD §3.7: "Finally, at least one `ClaimDocument` must be attached to the claim, or
    `ERR_INSUFFICIENT_DOCUMENTATION` is returned."

    Design: Corner/validations/approve_claim_without_documentation_rejected
    """
    ctx, claim = FX.setup_submitted_claim(claimed_amount_cents=1000000, with_document=False)
    pid = ctx["policy"]["id"]
    res = api.approve_claim(pid, claim["id"], _adj)
    validate_error(res, "ERR_INSUFFICIENT_DOCUMENTATION", 422)
    refreshed = validate_success(api.get_claim(pid, claim["id"], _uw), 200)
    assert refreshed["status"] == "SUBMITTED"
