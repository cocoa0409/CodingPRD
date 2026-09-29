"""One snapshot of state, two published numbers.

Four places in the Move Concierge contract publish two different figures over
the very same underlying rows: the readiness score under its pre- and
post-verification forms, an order's pessimistic deposit estimate against the
deposit the bureau finally demands, a placement's provisional commission
against its settled commission, and a duplicate score routed through the open
candidate pool against the same score routed through the cancelled pool.  Each
test below pins one side of one of those pairs to an exact value.
"""

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents,
    assert_created,
    assert_duplicate_score,
    assert_entry_types,
    assert_error,
    assert_ledger_net,
    assert_move_state,
    assert_order_dimensions,
    assert_page,
    assert_readiness_breakdown,
    assert_readiness_clamped,
    get_success_data,
)
from test_helpers.constants import CLOCK_STARTUP_DEFAULT
from test_helpers.types import (
    BlockedReason,
    ConsentGate,
    ConsentScope,
    CreditResult,
    CreditStatus,
    DuplicateFlag,
    HandoffStatus,
    LedgerEntryType,
    MoveLifecycleStatus,
    PlacementStatus,
    ProvisionStatus,
    ReadinessVariant,
    UtilityType,
)


def _move_with_one_scheduled_electric_order(api):
    """A move on a UTILITY_SETUP consent only, with its single order SCHEDULED.

    The children are identity PASSED today, one of one order done, no filing at
    all and exactly one of the two gate scopes covered.
    """
    bundle = fx.mapped_move(
        api,
        utility_types=[UtilityType.ELECTRIC.value],
        scopes=[ConsentScope.UTILITY_SETUP.value],
    )
    order = bundle["orders_by_type"][UtilityType.ELECTRIC.value]
    fx.schedule_order(api, order["id"], requested_service_date="2026-08-20")
    return bundle


# ---------------------------------------------------------------------------
# Readiness: the same four children weighted two different ways
# ---------------------------------------------------------------------------
def test_01_readiness_post_verification_form_scores_the_verified_move_at_70(api, ops_headers):
    """A SCHEDULING move reports 70 under the lifecycle-implied post variant.

    PRD: "it applies all four weights — identity 0.30, utility 0.30, filing
    0.20, consent 0.20 — with no renormalisation."

    Design: Difficulty/dual_variant_calc/readiness_pre_vs_post_verification_divergence
    """
    bundle = _move_with_one_scheduled_electric_order(api)
    move_id = bundle["move"]["id"]

    breakdown = fx.read_readiness(api, move_id)
    assert_readiness_breakdown(
        breakdown,
        variant=ReadinessVariant.POST_VERIFICATION.value,
        identity_component=100,
        utility_component=100,
        filing_component=0,
        consent_component=50,
        readiness_score=70,
    )

    move = fx.read_move(api, move_id)
    assert_move_state(
        move,
        lifecycle_status=MoveLifecycleStatus.SCHEDULING.value,
        consent_gate=ConsentGate.OPEN.value,
        readiness_score=70,
    )
    assert_readiness_clamped(move["readiness_score"])


def test_02_readiness_pre_verification_form_scores_the_same_children_at_57(api, ops_headers):
    """Overriding the variant renormalises the identical children down to 57.

    PRD: "the pre-verification form reports 57; the post-verification form
    reports 70 when the `identity_component` is 100"

    Design: Difficulty/dual_variant_calc/readiness_pre_vs_post_verification_divergence
    """
    bundle = _move_with_one_scheduled_electric_order(api)
    move_id = bundle["move"]["id"]

    post = fx.read_readiness(api, move_id, variant=ReadinessVariant.POST_VERIFICATION.value)
    pre = fx.read_readiness(api, move_id, variant=ReadinessVariant.PRE_VERIFICATION.value)

    assert_readiness_breakdown(
        pre,
        variant=ReadinessVariant.PRE_VERIFICATION.value,
        identity_component=100,
        utility_component=100,
        filing_component=0,
        consent_component=50,
        readiness_score=57,
    )
    assert post["readiness_score"] == 70, (
        f"expected the post-verification form to report 70, got {post['readiness_score']}"
    )
    assert pre["utility_component"] == post["utility_component"], (
        "both variants must read the same utility_component from the same children"
    )
    assert pre["consent_component"] == post["consent_component"], (
        "both variants must read the same consent_component from the same children"
    )
    assert pre["readiness_score"] != post["readiness_score"], (
        "the two variants must diverge on one identical snapshot of children"
    )


# ---------------------------------------------------------------------------
# Deposits: the pessimistic estimate against the bureau's final demand
# ---------------------------------------------------------------------------
def test_03_mapping_quotes_the_worst_case_deposit_estimate_of_22500_cents(api, ops_headers):
    """A CREDIT_SCORE_BASED order opens quoting 22500 with nothing yet due.

    PRD: "multiplies it by the worst score multiplier of 1.50, multiplies that
    by a neutral readiness multiplier of 1.00"

    Design: Difficulty/dual_variant_calc/deposit_estimate_vs_bureau_final_divergence
    """
    bundle = fx.mapped_move(
        api,
        utility_types=[UtilityType.ELECTRIC.value],
        scopes=[ConsentScope.UTILITY_SETUP.value],
    )
    order = bundle["orders_by_type"][UtilityType.ELECTRIC.value]

    assert_cents(order, "deposit_estimate_cents", 22500)
    assert_cents(order, "deposit_amount_cents", 0)
    assert_cents(order, "deposit_paid_cents", 0)
    assert order["readiness_snapshot"] is None, (
        "readiness_snapshot is only frozen when the credit check is dispatched"
    )
    assert_order_dimensions(
        order,
        provision_status=ProvisionStatus.DRAFT.value,
        credit_status=CreditStatus.PENDING_CHECK.value,
    )


def test_04_bureau_score_639_lands_a_final_deposit_of_18000_against_the_22500_estimate(
    api, ops_headers, gateway_headers
):
    """The final deposit diverges downward from the estimate written at mapping.

    PRD: "a `CREDIT_SCORE_BASED` provider with a bureau score of 639 and a
    frozen snapshot of 40 yields 18000 cents against the 22500-cent estimate
    written at mapping"

    Design: Difficulty/dual_variant_calc/deposit_estimate_vs_bureau_final_divergence
    """
    bundle = fx.mapped_move(
        api,
        utility_types=[UtilityType.ELECTRIC.value],
        scopes=[ConsentScope.UTILITY_SETUP.value],
    )
    order = bundle["orders_by_type"][UtilityType.ELECTRIC.value]
    handoff = fx.dispatch_credit_check(api, order["id"])

    handoff = fx.answer_bureau(api, handoff["id"], 639)

    assert handoff["result"] == CreditResult.DEPOSIT_REQUIRED.value, (
        f"a score of 639 is a DEPOSIT_REQUIRED result, got {handoff['result']}"
    )
    assert handoff["handoff_status"] == HandoffStatus.RESPONDED.value, (
        f"expected handoff_status RESPONDED, got {handoff['handoff_status']}"
    )
    assert handoff["score"] == 639, f"expected score 639, got {handoff['score']}"
    assert handoff["responded_at"] is not None, "responded_at must carry the answering instant"
    assert handoff["responded_at"].startswith("2026-08-01T00:00:00"), (
        f"responded_at must be the logical-clock instant, got {handoff['responded_at']}"
    )

    order = fx.read_order(api, order["id"])
    assert order["readiness_snapshot"] == 40, (
        f"expected the frozen readiness_snapshot 40, got {order['readiness_snapshot']}"
    )
    assert_cents(order, "deposit_amount_cents", 18000)
    assert_cents(order, "deposit_estimate_cents", 22500)
    assert order["deposit_amount_cents"] != order["deposit_estimate_cents"], (
        "the estimate and the final deposit must not converge"
    )
    assert_order_dimensions(
        order,
        provision_status=ProvisionStatus.DRAFT.value,
        credit_status=CreditStatus.DEPOSIT_DUE.value,
    )


# ---------------------------------------------------------------------------
# Duplicate detection: the same 0.80 score through two candidate pools
# ---------------------------------------------------------------------------
def _two_moves_scoring_exactly_080(api, headers, cancel_predecessor):
    """Ingest a predecessor move and then a second move that scores 0.80 on it.

    Both moves belong to one resident and both destinations sit in the same
    postal code and state with different address hashes, and the move dates are
    fifteen days apart inside a thirty-day dedupe window.
    """
    net = fx.build_network(api, clock=CLOCK_STARTUP_DEFAULT)
    second_destination = fx.create_destination_address(
        api, line1="915 Juniper St", unit=None
    )
    predecessor = fx.ingest_move(api, net, move_date="2026-08-20")
    if cancel_predecessor:
        predecessor = get_success_data(
            api.cancel_move(
                predecessor["id"],
                f.cancellation_payload(),
                headers,
            )
        )
    successor = fx.ingest_move(
        api,
        {**net, "destination_address": second_destination},
        move_date="2026-09-04",
    )
    return net, predecessor, successor


def test_05_open_predecessor_turns_the_080_score_into_a_suspected_duplicate(api, ops_headers):
    """Against a live predecessor the 0.80 score blocks the new move outright.

    PRD: "When the score reaches 0.80 or above, `duplicate_flag` becomes
    `SUSPECTED` and `blocked_reason` becomes `DUPLICATE_SUSPECTED`"

    Design: Difficulty/dual_variant_calc/duplicate_open_vs_cancelled_pool_divergence
    """
    _net, predecessor, successor = _two_moves_scoring_exactly_080(
        api, ops_headers, cancel_predecessor=False
    )

    assert_duplicate_score(successor, 0.80)
    assert_move_state(
        successor,
        lifecycle_status=MoveLifecycleStatus.INTAKE.value,
        duplicate_flag=DuplicateFlag.SUSPECTED.value,
        blocked_reason=BlockedReason.DUPLICATE_SUSPECTED.value,
    )
    assert successor["duplicate_candidate_move_id"] == predecessor["id"], (
        "the open pass must record the winning candidate it found"
    )
    assert successor["reactivation_candidate_move_id"] is None, (
        "the cancelled pass does not run once the open pass produced a SUSPECTED match"
    )

    refused = api.create_identity_verification(
        successor["id"], f.kba_attempt_payload(), ops_headers
    )
    assert_error(refused, ApiErrorId.DUPLICATE_MOVE_UNRESOLVED)


def test_06_cancelled_predecessor_turns_the_same_080_score_into_a_reactivation_hint(
    api, ops_headers
):
    """Through the cancelled pool the identical score never flags the move.

    PRD: "This pass never sets `duplicate_flag`, never sets
    `duplicate_candidate_move_id`, and never blocks the move."

    Design: Difficulty/dual_variant_calc/duplicate_open_vs_cancelled_pool_divergence
    """
    _net, predecessor, successor = _two_moves_scoring_exactly_080(
        api, ops_headers, cancel_predecessor=True
    )

    assert predecessor["lifecycle_status"] == MoveLifecycleStatus.CANCELLED.value, (
        f"expected the predecessor CANCELLED, got {predecessor['lifecycle_status']}"
    )
    assert_duplicate_score(successor, 0.80)
    assert_move_state(
        successor,
        lifecycle_status=MoveLifecycleStatus.INTAKE.value,
        duplicate_flag=DuplicateFlag.NONE.value,
        blocked_reason=BlockedReason.NONE.value,
    )
    assert successor["reactivation_candidate_move_id"] == predecessor["id"], (
        "the cancelled pass must record the re-book signal it found"
    )
    assert successor["duplicate_candidate_move_id"] is None, (
        "the open candidate pool was empty, so no candidate foreign key is written"
    )

    opened = api.create_identity_verification(
        successor["id"], f.kba_attempt_payload(), ops_headers
    )
    verification = assert_created(opened)
    assert verification["attempt_no"] == 1, (
        f"expected attempt_no 1, got {verification['attempt_no']}"
    )
    assert_move_state(
        fx.read_move(api, successor["id"]),
        lifecycle_status=MoveLifecycleStatus.IDENTITY_PENDING.value,
    )


# ---------------------------------------------------------------------------
# Referral revenue share: the provisional commission against the settled one
# ---------------------------------------------------------------------------
def test_07_conversion_posts_the_provisional_commission_of_27000_cents(api, admin_headers):
    """Conversion holds back a tenth, so the commission is 27000 not 30000.

    PRD: "a gross of 100000 cents against a 0.3000 revenue share yields a
    provisional commission of 27000 cents; a feed source on a 0.1750 share takes
    4725 cents of it"

    Design: Difficulty/dual_variant_calc/referral_share_provisional_vs_settled_divergence
    """
    bundle = fx.converted_referral(api, gross_revenue_cents=100000)
    placement = bundle["placement"]

    assert placement["placement_status"] == PlacementStatus.CONVERTED.value, (
        f"expected placement_status CONVERTED, got {placement['placement_status']}"
    )
    assert_cents(placement, "gross_revenue_cents", 100000)
    assert_cents(placement, "attributed_share_cents", 27000)
    assert_cents(placement, "feed_source_share_cents", 4725)

    entries = assert_page(
        api.list_ledger_entries(admin_headers, placement_id=placement["id"]),
        total_count=2,
        has_more=False,
    )
    assert_entry_types(
        entries,
        [LedgerEntryType.ACCRUAL.value, LedgerEntryType.FEED_SOURCE_SHARE.value],
    )
    assert_cents(entries[0], "amount_cents", 27000)
    assert_cents(entries[1], "amount_cents", -4725)
    assert_ledger_net(entries, placement)

    feed = fx.read_feed_source(api, bundle["feed_source"]["id"])
    assert_cents(feed, "accrued_share_cents", 4725)


def test_08_settlement_restates_the_shares_to_30000_and_posts_only_the_deltas(
    api, admin_headers
):
    """Settlement drops the holdback and journals the difference, not the total.

    PRD: "a settled gross of 100000 cents lifts the commission to 30000 and the
    feed share to 5250, so the ledger receives an `ADJUSTMENT` of positive 3000"

    Design: Difficulty/dual_variant_calc/referral_share_provisional_vs_settled_divergence
    """
    bundle = fx.converted_referral(api, gross_revenue_cents=100000)
    placement_id = bundle["placement"]["id"]

    settled = get_success_data(
        api.settle_placement(placement_id, f.settlement_payload(100000), admin_headers)
    )

    assert settled["placement_status"] == PlacementStatus.SETTLED.value, (
        f"expected placement_status SETTLED, got {settled['placement_status']}"
    )
    assert_cents(settled, "settled_gross_revenue_cents", 100000)
    assert_cents(settled, "attributed_share_cents", 30000)
    assert_cents(settled, "feed_source_share_cents", 5250)

    entries = assert_page(
        api.list_ledger_entries(admin_headers, placement_id=placement_id),
        total_count=4,
        has_more=False,
    )
    assert_entry_types(
        entries,
        [
            LedgerEntryType.ACCRUAL.value,
            LedgerEntryType.FEED_SOURCE_SHARE.value,
            LedgerEntryType.ADJUSTMENT.value,
            LedgerEntryType.FEED_SOURCE_SHARE_ADJUSTMENT.value,
        ],
    )
    assert_cents(entries[0], "amount_cents", 27000)
    assert_cents(entries[1], "amount_cents", -4725)
    assert_cents(entries[2], "amount_cents", 3000)
    assert_cents(entries[3], "amount_cents", -525)
    assert_ledger_net(entries, settled)

    feed = fx.read_feed_source(api, bundle["feed_source"]["id"])
    assert_cents(feed, "accrued_share_cents", 5250)
