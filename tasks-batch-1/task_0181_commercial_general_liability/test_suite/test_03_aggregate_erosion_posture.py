"""Aggregate-limit erosion, per-occurrence capping, policy posture, depth-3 cascades,
and the conservation invariants under deny / reserve-release.

Covers Difficulty queue instances for the per-occurrence-then-aggregate erosion order,
the incurred->aggregate->posture cascade, the 25% impairment boundary, deny-restores-room,
and reserve-set/release conservation; plus Corner queue instances for products-bucket
independence and the loss-run snapshot.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    assert_loss_run, assert_aggregate_conservation,
    factories, fixtures,
)

UW = TEST_USERS["underwriter_headers"]
ADMIN = TEST_USERS["insurer_admin_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]


# ===========================================================================
# Difficulty/combinatorial_formula/aggregate_erosion_per_occurrence_then_aggregate_cap
# ===========================================================================
def test_per_occurrence_cap_applied_before_aggregate(api):
    """PRD §3.6: "For each claim in that order, its incurred amount is first capped at the
    policy's `each_occurrence_limit_cents` to yield a per-occurrence-capped figure."
    PRD §3.6: "The per-occurrence cap is therefore always applied before the aggregate cap."

    Design: Difficulty/combinatorial_formula/aggregate_erosion_per_occurrence_then_aggregate_cap
    """
    insurer, insured, policy = fixtures.create_in_force_policy(policy_number="CGL-0002")
    claim = fixtures.open_claim(policy["id"], claimant_name="Injured C",
                                loss_type="BODILY_INJURY",
                                occurrence_date="2026-03-01T00:00:00.000Z",
                                reported_date="2026-03-05T00:00:00.000Z")
    # $1.5M reserve; each_occ $1M cap -> recognized 100000000; general agg $2M -> remaining $1M.
    fixtures.post_first_reserve(claim["id"], 150000000)
    after_claim = validate_success(api.get_claim(claim["id"], ADJ), 200)
    assert after_claim["incurred_cents"] == 150000000
    assert after_claim["recognized_incurred_cents"] == 100000000
    pol = validate_success(api.get_policy(policy["id"], UW), 200)
    assert pol["general_aggregate_remaining_cents"] == 100000000
    assert pol["products_aggregate_remaining_cents"] == 100000000


def test_recognized_incurred_capped_at_each_occurrence_limit(api):
    """PRD §3.6: "its incurred amount is first capped at the policy's `each_occurrence_limit_cents`
    to yield a per-occurrence-capped figure."
    PRD §3.6: "that recognized amount is added to the running total for its bucket and stored as
    the claim's `recognized_incurred_cents`."

    Design: Difficulty/combinatorial_formula/aggregate_erosion_per_occurrence_then_aggregate_cap
    """
    # A single GENERAL claim whose incurred exceeds each_occurrence but stays under the aggregate:
    # recognized must equal the per-occurrence limit, not the full incurred.
    insurer, insured, policy = fixtures.create_in_force_policy(policy_number="CGL-OCCAP")
    claim = fixtures.open_claim(policy["id"], claimant_name="BigLoss",
                                loss_type="PROPERTY_DAMAGE",
                                occurrence_date="2026-03-01T00:00:00.000Z",
                                reported_date="2026-03-05T00:00:00.000Z")
    fixtures.post_first_reserve(claim["id"], 120000000)  # > each_occ $1M, < gen_agg $2M
    after_claim = validate_success(api.get_claim(claim["id"], ADJ), 200)
    assert after_claim["recognized_incurred_cents"] == 100000000
    pol = validate_success(api.get_policy(policy["id"], UW), 200)
    assert pol["general_aggregate_remaining_cents"] == 100000000


# ===========================================================================
# Difficulty/transitive_cascade/claim_txn_cascades_incurred_aggregate_posture
# ===========================================================================
def test_reserve_cascades_incurred_aggregate_and_posture(api):
    """PRD §2.6: "When a claim transaction is posted, the claim's incurred figures are
    recomputed, the policy's two aggregate-remaining figures are recomputed, and the policy's
    `posture` is re-derived, all in the same request."
    PRD §3.6: "Otherwise the posture is `HEALTHY`."

    Design: Difficulty/transitive_cascade/claim_txn_cascades_incurred_aggregate_posture
    """
    insurer, insured, policy = fixtures.create_in_force_policy(policy_number="CGL-0006")
    claim = fixtures.open_claim(policy["id"], claimant_name="Injured E",
                                loss_type="PROPERTY_DAMAGE",
                                occurrence_date="2026-03-01T00:00:00.000Z",
                                reported_date="2026-03-02T00:00:00.000Z")
    fixtures.post_first_reserve(claim["id"], 180000000)
    after_claim = validate_success(api.get_claim(claim["id"], ADJ), 200)
    assert after_claim["incurred_cents"] == 180000000
    assert after_claim["recognized_incurred_cents"] == 100000000  # per-occurrence capped
    pol = validate_success(api.get_policy(policy["id"], UW), 200)
    assert pol["general_aggregate_remaining_cents"] == 100000000
    # remaining 100000000 > impairment floor floor(200000000/4)=50000000 -> HEALTHY.
    assert pol["posture"] == "HEALTHY"


def test_reserve_cascade_drives_posture_to_impaired(api):
    """PRD §2.6: "the policy's two aggregate-remaining figures are recomputed, and the policy's
    `posture` is re-derived, all in the same request."
    PRD §3.6: "if either bucket's remaining amount has fallen to one quarter or less of that
    bucket's limit ... the posture is `IMPAIRED`."

    Design: Difficulty/transitive_cascade/claim_txn_cascades_incurred_aggregate_posture
    """
    # each_occurrence raised to $2M so a single $1.6M GENERAL claim is recognized in full,
    # leaving general remaining 40000000 <= floor(200000000/4)=50000000 -> IMPAIRED.
    insurer, insured, policy = fixtures.create_in_force_policy(
        policy_number="CGL-CASC-IMP", each_occurrence_limit_cents=200000000)
    claim = fixtures.open_claim(policy["id"], claimant_name="HeavyGeneral",
                                loss_type="BODILY_INJURY",
                                occurrence_date="2026-03-01T00:00:00.000Z",
                                reported_date="2026-03-02T00:00:00.000Z")
    fixtures.post_first_reserve(claim["id"], 160000000)
    after_claim = validate_success(api.get_claim(claim["id"], ADJ), 200)
    assert after_claim["recognized_incurred_cents"] == 160000000
    pol = validate_success(api.get_policy(policy["id"], UW), 200)
    assert pol["general_aggregate_remaining_cents"] == 40000000
    assert pol["posture"] == "IMPAIRED"


# ===========================================================================
# Difficulty/boundary_precision_check/posture_impairment_at_exactly_25_percent_remaining
# ===========================================================================
def test_posture_impaired_at_exactly_quarter_remaining(api):
    """PRD §3.6: "if either bucket's remaining amount has fallen to one quarter or less of that
    bucket's limit ... the posture is `IMPAIRED`. At exactly one quarter remaining the policy is
    impaired."

    Design: Difficulty/boundary_precision_check/posture_impairment_at_exactly_25_percent_remaining
    """
    insurer, insured, policy = fixtures.create_in_force_policy(policy_number="CGL-0010")
    pid = policy["id"]
    # Claim A GENERAL $1M (recognized 100000000); claim B GENERAL $500k (recognized 50000000)
    # -> general remaining = 200000000 - 150000000 = 50000000 == floor(200000000/4).
    ca = fixtures.open_claim(pid, claimant_name="A", loss_type="BODILY_INJURY",
                             occurrence_date="2026-03-01T00:00:00.000Z",
                             reported_date="2026-03-02T00:00:00.000Z")
    fixtures.post_first_reserve(ca["id"], 100000000)
    cb = fixtures.open_claim(pid, claimant_name="B", loss_type="PROPERTY_DAMAGE",
                             occurrence_date="2026-03-03T00:00:00.000Z",
                             reported_date="2026-03-04T00:00:00.000Z")
    fixtures.post_first_reserve(cb["id"], 50000000)
    pol = validate_success(api.get_policy(pid, UW), 200)
    assert pol["general_aggregate_remaining_cents"] == 50000000
    assert pol["posture"] == "IMPAIRED"


def test_posture_healthy_just_above_quarter_remaining(api):
    """PRD §3.6: "the general remaining is at or below one quarter of `general_aggregate_limit_cents`
    ... the posture is `IMPAIRED`. At exactly one quarter remaining the policy is impaired.
    Otherwise the posture is `HEALTHY`."

    Design: Difficulty/boundary_precision_check/posture_impairment_at_exactly_25_percent_remaining
    """
    # Drive general remaining to 50000001 (one cent above the 50000000 floor) -> HEALTHY.
    insurer, insured, policy = fixtures.create_in_force_policy(policy_number="CGL-BND-PLUS")
    pid = policy["id"]
    ca = fixtures.open_claim(pid, claimant_name="A", loss_type="BODILY_INJURY",
                             occurrence_date="2026-03-01T00:00:00.000Z",
                             reported_date="2026-03-02T00:00:00.000Z")
    fixtures.post_first_reserve(ca["id"], 100000000)
    cb = fixtures.open_claim(pid, claimant_name="B", loss_type="PROPERTY_DAMAGE",
                             occurrence_date="2026-03-03T00:00:00.000Z",
                             reported_date="2026-03-04T00:00:00.000Z")
    fixtures.post_first_reserve(cb["id"], 49999999)
    pol = validate_success(api.get_policy(pid, UW), 200)
    # general remaining = 200000000 - 100000000 - 49999999 = 50000001 > 50000000 floor.
    assert pol["general_aggregate_remaining_cents"] == 50000001
    assert pol["posture"] == "HEALTHY"


# ===========================================================================
# Difficulty/compensating_invariant/deny_claim_restores_general_aggregate_room
# ===========================================================================
def test_deny_claim_restores_general_aggregate_room(api):
    """PRD §3.7: "Denial moves the claim to `DENIED` and, because a denied claim contributes
    nothing to erosion, drops its `recognized_incurred_cents` to zero and cascades aggregate
    erosion and posture so that the general or products room it had consumed returns to the
    policy."

    Design: Difficulty/compensating_invariant/deny_claim_restores_general_aggregate_room
    """
    insurer, insured, policy = fixtures.create_in_force_policy(policy_number="CGL-0016")
    pid = policy["id"]
    claim = fixtures.open_claim(pid, claimant_name="Disputed H", loss_type="PROPERTY_DAMAGE",
                                occurrence_date="2026-03-01T00:00:00.000Z",
                                reported_date="2026-03-02T00:00:00.000Z")
    fixtures.post_first_reserve(claim["id"], 90000000)
    before = validate_success(api.get_policy(pid, UW), 200)
    assert before["general_aggregate_remaining_cents"] == 110000000  # 200000000 - 90000000

    denied = validate_success(api.deny_claim(claim["id"], ADJ), 200)
    assert denied["status"] == "DENIED"
    assert denied["recognized_incurred_cents"] == 0
    after = validate_success(api.get_policy(pid, UW), 200)
    assert after["general_aggregate_remaining_cents"] == 200000000  # room fully restored


def test_deny_claim_conservation_invariant_holds(api):
    """PRD §3.6: "`general_aggregate_remaining_cents` is the general limit less the total
    recognized in the `GENERAL` bucket (floored at zero)".
    PRD §3.7: "drops its `recognized_incurred_cents` to zero and cascades aggregate erosion and
    posture so that the general or products room it had consumed returns to the policy."

    Design: Difficulty/compensating_invariant/deny_claim_restores_general_aggregate_room
    """
    insurer, insured, policy = fixtures.create_in_force_policy(policy_number="CGL-INV-DENY")
    pid = policy["id"]
    claim = fixtures.open_claim(pid, claimant_name="ConservH", loss_type="BODILY_INJURY",
                                occurrence_date="2026-03-01T00:00:00.000Z",
                                reported_date="2026-03-02T00:00:00.000Z")
    fixtures.post_first_reserve(claim["id"], 90000000)
    after_set = validate_success(api.get_policy(pid, UW), 200)
    claim_set = validate_success(api.get_claim(claim["id"], ADJ), 200)
    # remaining + recognized == limit while reserved.
    assert_aggregate_conservation(after_set, claim_set["recognized_incurred_cents"], 0)

    validate_success(api.deny_claim(claim["id"], ADJ), 200)
    after_deny = validate_success(api.get_policy(pid, UW), 200)
    # After deny, recognized over GENERAL == 0, so remaining == limit.
    assert_aggregate_conservation(after_deny, 0, 0)


# ===========================================================================
# Difficulty/compensating_invariant/reserve_set_then_release_conserves_claim_incurred
# ===========================================================================
def test_reserve_set_then_release_conserves_incurred(api):
    """PRD §3.6: "The open reserve is the sum of all `RESERVE_SET` amounts minus the sum of all
    `RESERVE_RELEASE` amounts, and is itself floored at zero. The incurred figure is then the
    open reserve plus the sum of all `PAYMENT` amounts minus the sum of all `RECOVERY` amounts,
    with the whole figure floored at zero."

    Design: Difficulty/compensating_invariant/reserve_set_then_release_conserves_claim_incurred
    """
    insurer, insured, policy = fixtures.create_in_force_policy(policy_number="CGL-0017")
    pid = policy["id"]
    claim = fixtures.open_claim(pid, claimant_name="Settled I", loss_type="BODILY_INJURY",
                               occurrence_date="2026-02-01T00:00:00.000Z",
                               reported_date="2026-02-02T00:00:00.000Z")
    fixtures.post_first_reserve(claim["id"], 40000000)
    fixtures.post_transaction_occ(pid, claim["id"], "PAYMENT", 40000000)
    # baseline incurred = open reserve 40000000 + payments 40000000 = 80000000.
    fixtures.post_transaction_occ(pid, claim["id"], "RESERVE_SET", 30000000)
    after_set = validate_success(api.get_claim(claim["id"], ADJ), 200)
    # open reserve 70000000 + payments 40000000 = 110000000.
    assert after_set["incurred_cents"] == 110000000

    fixtures.post_transaction_occ(pid, claim["id"], "RESERVE_RELEASE", 30000000)
    after_release = validate_success(api.get_claim(claim["id"], ADJ), 200)
    # baseline restored: open reserve back to 40000000 + payments 40000000 = 80000000.
    assert after_release["incurred_cents"] == 80000000


def test_reserve_release_returns_open_reserve_to_prior_level(api):
    """PRD §3.6: "The open reserve is the sum of all `RESERVE_SET` amounts minus the sum of all
    `RESERVE_RELEASE` amounts, and is itself floored at zero."

    Design: Difficulty/compensating_invariant/reserve_set_then_release_conserves_claim_incurred
    """
    # A pure reserve-set-then-release pair with no payments: incurred returns to the original
    # reserve level (a different starting point than the payment-baseline variant above).
    insurer, insured, policy = fixtures.create_in_force_policy(policy_number="CGL-RSV-CONS")
    pid = policy["id"]
    claim = fixtures.open_claim(pid, claimant_name="PureReserve", loss_type="BODILY_INJURY",
                               occurrence_date="2026-02-01T00:00:00.000Z",
                               reported_date="2026-02-02T00:00:00.000Z")
    fixtures.post_first_reserve(claim["id"], 20000000)
    fixtures.post_transaction_occ(pid, claim["id"], "RESERVE_SET", 25000000)
    mid = validate_success(api.get_claim(claim["id"], ADJ), 200)
    assert mid["incurred_cents"] == 45000000  # open reserve 20000000 + 25000000
    fixtures.post_transaction_occ(pid, claim["id"], "RESERVE_RELEASE", 25000000)
    end = validate_success(api.get_claim(claim["id"], ADJ), 200)
    assert end["incurred_cents"] == 20000000  # back to original reserve


# ===========================================================================
# Corner/calculations/products_bucket_independence_from_general
# ===========================================================================
def test_products_bucket_independence_from_general(api):
    """PRD §2.7: "products losses never erode the general aggregate and vice versa".
    PRD §3.6: "The two buckets are conserved entirely separately."

    Design: Corner/calculations/products_bucket_independence_from_general
    """
    insurer, insured, policy = fixtures.create_in_force_policy(policy_number="CGL-C13")
    pid = policy["id"]
    claim = fixtures.open_claim(pid, claimant_name="Prod M", loss_type="PRODUCTS_COMPLETED_OPS",
                                occurrence_date="2026-03-01T00:00:00.000Z",
                                reported_date="2026-03-02T00:00:00.000Z")
    fixtures.post_first_reserve(claim["id"], 90000000)  # erodes PRODUCTS only
    pol = validate_success(api.get_policy(pid, UW), 200)
    assert pol["products_aggregate_remaining_cents"] == 10000000   # 100000000 - 90000000
    assert pol["general_aggregate_remaining_cents"] == 200000000   # untouched
    # products remaining 10000000 <= floor(100000000/4)=25000000 -> IMPAIRED via products only.
    assert pol["posture"] == "IMPAIRED"


# ===========================================================================
# Corner/calculations/loss_run_snapshot_totals_and_counts
# ===========================================================================
def test_loss_run_snapshot_totals_and_counts(api):
    """PRD §3.9: "Over the included claims the snapshot records `total_incurred_cents` as the
    sum of their `incurred_cents`, `general_incurred_cents` as the incurred sum over those in the
    `GENERAL` bucket, `products_incurred_cents` as the incurred sum over those in the `PRODUCTS`
    bucket, `claim_count` as the number of included claims, and `open_claim_count` as the number
    of included claims not in `CLOSED` or `DENIED`."

    Design: Corner/calculations/loss_run_snapshot_totals_and_counts
    """
    insurer, insured, policy = fixtures.create_in_force_policy(policy_number="CGL-C14")
    pid = policy["id"]
    c1 = fixtures.open_claim(pid, claimant_name="Gen N", loss_type="BODILY_INJURY",
                             occurrence_date="2026-03-01T00:00:00.000Z",
                             reported_date="2026-03-02T00:00:00.000Z")
    fixtures.post_first_reserve(c1["id"], 50000000)
    c2 = fixtures.open_claim(pid, claimant_name="Prod N", loss_type="PRODUCTS_COMPLETED_OPS",
                             occurrence_date="2026-03-03T00:00:00.000Z",
                             reported_date="2026-03-04T00:00:00.000Z")
    fixtures.post_transaction_occ(pid, c2["id"], "RESERVE_SET", 30000000)
    lr = validate_success(api.generate_loss_run(pid, ADJ), 201)
    assert_loss_run(lr)
    assert lr["total_incurred_cents"] == 80000000
    assert lr["general_incurred_cents"] == 50000000
    assert lr["products_incurred_cents"] == 30000000
    assert lr["claim_count"] == 2
    assert lr["open_claim_count"] == 2
