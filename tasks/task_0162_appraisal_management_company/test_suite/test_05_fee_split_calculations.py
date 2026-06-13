"""Fee split: provisional vs final variants, per-component rounding, floor clamp,
and the fee-conservation invariant.

Covers queue A (Difficulty) dual_variant_calc, combinatorial_formula, and
compensating_invariant instances, plus queue B calculations (floor clamp).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, factories, fixtures, assert_fee_conservation,
)

COORD = TEST_USERS["coordinator_headers"]
REVIEWER = TEST_USERS["compliance_reviewer_headers"]


def test_provisional_fee_split_at_placement(api):
    """PRD §3.6: "The **provisional** variant is the one created at placement, before any
    revision, when the assignment's `revision_round` is zero: the penalty is zero, only
    the gross appraiser amount applies, and the `variant` field reads `PROVISIONAL`."
    PRD §3.6: "the **base** is the order's `order_fee_cents` multiplied by the assigned
    appraiser's `base_fee_share_pct`, rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/fee_split_provisional_vs_final_diverges_after_revision
    """
    # fee 50000 share 0.60 -> base 30000; no rush, no revision.
    # PRD §3.6 keys the provisional base on "the assigned appraiser's base_fee_share_pct",
    # so the appraiser share is populated once an appraiser is assigned; the split stays
    # PROVISIONAL until completion. Assign before reading the provisional split.
    base = fixtures.setup_order_ready_to_assign(order_fee_cents=50000, base_fee_share_pct=0.60)
    fixtures.assign_order(base["order"]["id"], base["order"]["version"])
    fee_split = validate_success(api.get_order_fee_split(base["order"]["id"], COORD), 200)[0]
    assert fee_split["variant"] == "PROVISIONAL", f"placement split must be PROVISIONAL, got {fee_split['variant']}"
    assert fee_split["appraiser_fee_cents"] == 30000, (
        f"provisional appraiser share must be 50000*0.60=30000, got {fee_split['appraiser_fee_cents']}"
    )
    assert fee_split["amc_fee_cents"] == 20000, f"amc residual must be 20000, got {fee_split['amc_fee_cents']}"
    assert fee_split["revision_penalty_cents"] == 0, "provisional penalty must be 0"


def test_final_fee_split_diverges_after_one_revision(api):
    """PRD §3.6: "The **final** variant is computed when the order completes: the penalty
    reflects the assignment's final `revision_round`, and the `variant` field reads
    `FINAL`. The two variants differ in cents whenever the order went through one or more
    revision rounds."
    PRD §3.6: "The appraiser's share is then the gross appraiser amount minus the
    accumulated penalty, but never below the appraiser floor of 5000 cents".

    Design: Difficulty/dual_variant_calc/fee_split_provisional_vs_final_diverges_after_revision
    """
    # fee 50000 share 0.60 -> base 30000; one revision penalty 2500 -> final appraiser 27500.
    res = fixtures.setup_order_completed_after_one_revision(order_fee_cents=50000, base_fee_share_pct=0.60)
    fee_split = res["fee_split"]
    assert fee_split["variant"] == "FINAL", f"completed split must be FINAL, got {fee_split['variant']}"
    assert fee_split["appraiser_fee_cents"] == 27500, (
        f"final appraiser share must be 30000-2500=27500, got {fee_split['appraiser_fee_cents']}"
    )
    assert fee_split["amc_fee_cents"] == 22500, f"amc residual must be 22500, got {fee_split['amc_fee_cents']}"
    assert fee_split["revision_penalty_cents"] == 2500, (
        f"cumulative penalty after one round must be 2500, got {fee_split['revision_penalty_cents']}"
    )


def test_fee_split_rounding_per_component_with_rush(api):
    """PRD §3.6: "with each named component independently rounded half-up to whole cents
    before the components are combined."
    PRD §3.6: "a **rush premium** applies only when the order's `rush` flag is set: it is
    the `order_fee_cents` multiplied by the rush premium fraction of ten percent, rounded
    half-up to whole cents".

    Design: Difficulty/combinatorial_formula/fee_split_rounding_order_pinned_per_component
    """
    # fee 80000 share 0.55 rush -> base 44000, rush_premium 8000, appraiser 52000.
    # PRD §3.6 bases the provisional appraiser share on the assigned appraiser; assign first.
    base = fixtures.setup_order_ready_to_assign(order_fee_cents=80000, base_fee_share_pct=0.55, rush=True)
    fixtures.assign_order(base["order"]["id"], base["order"]["version"])
    fee_split = validate_success(api.get_order_fee_split(base["order"]["id"], COORD), 200)[0]
    assert fee_split["variant"] == "PROVISIONAL", f"placement split must be PROVISIONAL, got {fee_split['variant']}"
    assert fee_split["appraiser_fee_cents"] == 52000, (
        f"per-component appraiser share must be base 44000 + rush 8000 = 52000, "
        f"got {fee_split['appraiser_fee_cents']}"
    )
    assert fee_split["amc_fee_cents"] == 28000, f"amc residual must be 28000, got {fee_split['amc_fee_cents']}"


def test_fee_split_base_component_rounded_without_rush(api):
    """PRD §3.6: "the **base** is the order's `order_fee_cents` multiplied by the assigned
    appraiser's `base_fee_share_pct`, rounded half-up to whole cents."
    PRD §3.6: "when the order is not a rush, the rush premium is zero. The gross appraiser
    amount is the base plus the rush premium."

    Design: Difficulty/combinatorial_formula/fee_split_rounding_order_pinned_per_component
    """
    # fee 50000 share 0.55, no rush -> base round_half_up(27500.0)=27500; no rush premium.
    # PRD §3.6 bases the provisional appraiser share on the assigned appraiser; assign first.
    base = fixtures.setup_order_ready_to_assign(order_fee_cents=50000, base_fee_share_pct=0.55)
    fixtures.assign_order(base["order"]["id"], base["order"]["version"])
    fee_split = validate_success(api.get_order_fee_split(base["order"]["id"], COORD), 200)[0]
    assert fee_split["appraiser_fee_cents"] == 27500, (
        f"non-rush appraiser share must be base 50000*0.55=27500 (no rush premium), "
        f"got {fee_split['appraiser_fee_cents']}"
    )
    assert fee_split["amc_fee_cents"] == 22500, f"amc residual must be 22500, got {fee_split['amc_fee_cents']}"


def test_appraiser_floor_clamps_share_after_three_revisions(api):
    """PRD §3.6: "The appraiser's share is then the gross appraiser amount minus the
    accumulated penalty, but never below the appraiser floor of 5000 cents — the share is
    the larger of those two values. Finally, the AMC's share is the conserved residual:
    the order's `order_fee_cents` minus the appraiser's share."

    Design: Corner/calculations/fee_split_floor_clamps_appraiser_share
    """
    # fee 20000 share 0.30 -> base 6000; 3 revisions penalty 3*1000=3000; raw 3000 -> clamped 5000.
    base = fixtures.setup_order_ready_to_assign(order_fee_cents=20000, base_fee_share_pct=0.30)
    order = base["order"]
    appraiser = base["appraiser"]
    asg = fixtures.assign_order(order["id"], order["version"])
    fixtures.accept_assignment(asg["id"], appraiser["id"])
    report = fixtures.submit_report(asg["id"], appraiser["id"], comparable_count=2)
    # Three FAIL->resubmit revision rounds (USPAP-deficient); the last resubmit carries
    # adequate comps so the final review can pass.
    for round_idx in range(3):
        cr = fixtures.open_review(report["id"])
        fixtures.finalize_review(cr["id"], finding_codes=["USPAP_1004_MIN_COMPS"])  # FAIL
        resubmit_comps = 4 if round_idx == 2 else 2
        fixtures.submit_report(asg["id"], appraiser["id"], comparable_count=resubmit_comps)
    cr_pass = fixtures.open_review(report["id"])
    fixtures.finalize_review(cr_pass["id"])  # PASS -> DELIVERED
    v = fixtures.current_order_version(order["id"])
    validate_success(api.complete_order(order["id"], factories.assignment_create_payload(v), COORD), 200)

    fee_split = validate_success(api.get_order_fee_split(order["id"], COORD), 200)[0]
    assert fee_split["appraiser_fee_cents"] == 5000, (
        f"appraiser share must clamp up to the 5000 floor, got {fee_split['appraiser_fee_cents']}"
    )
    assert fee_split["amc_fee_cents"] == 15000, f"amc residual must be 20000-5000=15000, got {fee_split['amc_fee_cents']}"


def test_fee_conservation_holds_after_revision_and_completion(api):
    """PRD §2.7: "A standing invariant governs every fee split: the appraiser's share and
    the AMC's share must always sum to the order's fee. The AMC share is therefore never
    computed independently; it is always the residual obtained by subtracting
    `appraiser_fee_cents` from the order's `order_fee_cents`."

    Design: Difficulty/compensating_invariant/fee_conservation_appraiser_plus_amc_equals_order_fee
    """
    res = fixtures.setup_order_completed_after_one_revision(order_fee_cents=50000, base_fee_share_pct=0.60)
    fee_split = res["fee_split"]
    assert fee_split["appraiser_fee_cents"] == 27500, f"got {fee_split['appraiser_fee_cents']}"
    assert fee_split["amc_fee_cents"] == 22500, f"got {fee_split['amc_fee_cents']}"
    assert_fee_conservation(fee_split, 50000)


def test_fee_conservation_holds_at_provisional_placement(api):
    """PRD §2.7: "A standing invariant governs every fee split: the appraiser's share and
    the AMC's share must always sum to the order's fee. The AMC share is therefore never
    computed independently; it is always the residual obtained by subtracting
    `appraiser_fee_cents` from the order's `order_fee_cents`."

    Design: Difficulty/compensating_invariant/fee_conservation_appraiser_plus_amc_equals_order_fee
    """
    # The conservation invariant must hold at the PROVISIONAL placement split too.
    # PRD §3.6 bases the provisional appraiser share on the assigned appraiser; assign first.
    base = fixtures.setup_order_ready_to_assign(order_fee_cents=50000, base_fee_share_pct=0.60)
    fixtures.assign_order(base["order"]["id"], base["order"]["version"])
    fee_split = validate_success(api.get_order_fee_split(base["order"]["id"], COORD), 200)[0]
    assert fee_split["variant"] == "PROVISIONAL", f"got {fee_split['variant']}"
    assert fee_split["appraiser_fee_cents"] == 30000, f"got {fee_split['appraiser_fee_cents']}"
    assert_fee_conservation(fee_split, 50000)
