"""Formulas that compose several inputs and pin the order they run in.

Three arithmetic surfaces in the Move Concierge contract refuse to be reduced
to a single multiplication: the readiness blend, which rounds four components
before weighting them and rounds the weighted sum afterwards, dropping and
renormalising a term when identity has not cleared; the feed source's running
balance, which rounds every placement's cut before adding the cuts together;
and the deposit, which multiplies a base by two multipliers read from two
different instants.  Each test below drives one of those formulas end to end
and asserts the exact integer it must produce.
"""

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_cents,
    assert_entry_types,
    assert_move_state,
    assert_order_dimensions,
    assert_page,
    assert_readiness_breakdown,
    assert_readiness_clamped,
)
from test_helpers.types import (
    ConsentGate,
    ConsentScope,
    CreditStatus,
    FilingStatus,
    LedgerEntryType,
    MoveLifecycleStatus,
    PayoutModel,
    PlacementStatus,
    ProvisionStatus,
    ReadinessVariant,
    UtilityType,
)


# ---------------------------------------------------------------------------
# Readiness: four components, two weight sets, one divisor
# ---------------------------------------------------------------------------
def test_01_intake_move_renormalises_a_lone_consent_term_up_to_29(api, ops_headers):
    """A household with both gate consents and nothing else scores 29, not 20.

    The only non-zero component is consent at 100, worth 20 of the weighted
    sum; dividing that sum by the renormalisation divisor lifts the reported
    score above the raw weighted total.

    PRD: "it drops the identity term entirely and renormalises the remaining
    three weights"

    Design: Difficulty/combinatorial_formula/readiness_weight_renormalization_with_clamp
    """
    network = fx.build_network(api)
    fx.grant_consents(
        api,
        network["resident"]["id"],
        [ConsentScope.UTILITY_SETUP.value, ConsentScope.USPS_FILING.value],
    )
    move = fx.ingest_move(api, network, move_date="2026-08-20")

    assert_move_state(
        move,
        lifecycle_status=MoveLifecycleStatus.INTAKE.value,
        consent_gate=ConsentGate.OPEN.value,
        readiness_score=29,
    )
    assert_readiness_clamped(move["readiness_score"])

    implied = fx.read_readiness(api, move["id"])
    assert_readiness_breakdown(
        implied,
        variant=ReadinessVariant.PRE_VERIFICATION.value,
        identity_component=0,
        utility_component=0,
        filing_component=0,
        consent_component=100,
        readiness_score=29,
    )

    overridden = fx.read_readiness(
        api, move["id"], variant=ReadinessVariant.POST_VERIFICATION.value
    )
    assert_readiness_breakdown(
        overridden,
        variant=ReadinessVariant.POST_VERIFICATION.value,
        identity_component=0,
        utility_component=0,
        filing_component=0,
        consent_component=100,
        readiness_score=20,
    )


def test_02_all_four_components_blend_to_77_and_fall_to_47_when_identity_lapses(
    api, ops_headers
):
    """Half the orders done, a submitted filing and both consents blend to 77.

    Once the identity window lapses the identity term is worth nothing, the
    post-verification blend drops to 47, and the renormalised form reports 67 on
    exactly the same children.

    PRD: "components are rounded to 0 decimal places with round-half-up"

    Design: Difficulty/combinatorial_formula/readiness_weight_renormalization_with_clamp
    """
    bundle = fx.mapped_move(
        api,
        utility_types=[UtilityType.ELECTRIC.value, UtilityType.WATER.value],
        scopes=[ConsentScope.UTILITY_SETUP.value, ConsentScope.USPS_FILING.value],
    )
    move_id = bundle["move"]["id"]
    electric = bundle["orders_by_type"][UtilityType.ELECTRIC.value]
    fx.schedule_order(api, electric["id"], requested_service_date="2026-08-20")
    filing = fx.draft_filing(api, move_id, forward_start_date="2026-08-20")
    filing = fx.submit_filing(api, filing["id"])
    assert filing["status"] == FilingStatus.SUBMITTED.value, (
        f"expected the filing SUBMITTED, got {filing['status']}"
    )

    assert_readiness_breakdown(
        fx.read_readiness(api, move_id),
        variant=ReadinessVariant.POST_VERIFICATION.value,
        identity_component=100,
        utility_component=50,
        filing_component=60,
        consent_component=100,
        readiness_score=77,
    )
    assert_move_state(fx.read_move(api, move_id), readiness_score=77)

    fx.set_clock(api, "2026-09-01T00:00:00Z")

    lapsed = fx.read_readiness(api, move_id)
    assert_readiness_breakdown(
        lapsed,
        variant=ReadinessVariant.POST_VERIFICATION.value,
        identity_component=0,
        utility_component=50,
        filing_component=60,
        consent_component=100,
        readiness_score=47,
    )
    assert_readiness_clamped(lapsed["readiness_score"])

    renormalised = fx.read_readiness(
        api, move_id, variant=ReadinessVariant.PRE_VERIFICATION.value
    )
    assert_readiness_breakdown(
        renormalised,
        variant=ReadinessVariant.PRE_VERIFICATION.value,
        identity_component=0,
        utility_component=50,
        filing_component=60,
        consent_component=100,
        readiness_score=67,
    )
    assert_readiness_clamped(renormalised["readiness_score"])


# ---------------------------------------------------------------------------
# The feed source balance: round each placement's cut, then add
# ---------------------------------------------------------------------------
def _two_conversions_of_3715_cents(api):
    """Convert one internet and one insurance referral, each on a gross of 3715.

    Both partners pay a 0.3000 revenue share, so both placements produce the
    same commission and the same feed-source cut through the same waterfall.
    """
    verified = fx.verified_move(api)
    internet = fx.add_internet_partner(api)
    insurance = fx.create_partner(
        api,
        f.insurance_partner_payload(
            payout_model=PayoutModel.REV_SHARE_PCT.value, rev_share_pct=0.3
        ),
    )
    first = fx.converted_referral(
        api, gross_revenue_cents=3715, bundle=verified, partner=internet
    )
    second = fx.converted_referral(
        api, gross_revenue_cents=3715, bundle=first, partner=insurance
    )
    return first, second


def test_03_each_conversion_of_3715_cents_rounds_its_own_cut_to_176(api, admin_headers):
    """Both placements round the feed source's cut to 176 cents individually.

    PRD: "each placement's share is rounded first, then the rounded figures are
    added"

    Design: Difficulty/combinatorial_formula/feed_source_share_round_per_placement_then_sum
    """
    first, second = _two_conversions_of_3715_cents(api)

    for bundle in (first, second):
        placement = bundle["placement"]
        assert placement["placement_status"] == PlacementStatus.CONVERTED.value, (
            f"expected placement_status CONVERTED, got {placement['placement_status']}"
        )
        assert_cents(placement, "gross_revenue_cents", 3715)
        assert_cents(placement, "attributed_share_cents", 1003)
        assert_cents(placement, "feed_source_share_cents", 176)

        entries = assert_page(
            api.list_ledger_entries(admin_headers, placement_id=placement["id"]),
            total_count=2,
            has_more=False,
        )
        assert_entry_types(
            entries,
            [LedgerEntryType.ACCRUAL.value, LedgerEntryType.FEED_SOURCE_SHARE.value],
        )
        assert_cents(entries[0], "amount_cents", 1003)
        assert_cents(entries[1], "amount_cents", -176)

    assert first["placement"]["vertical"] != second["placement"]["vertical"], (
        "the two placements must sit in different verticals to coexist on one move"
    )


def test_04_the_feed_source_balance_settles_on_352_rather_than_351(api, admin_headers):
    """Adding two already-rounded cuts gives 352, one cent above a terminal round.

    PRD: "each round to 176 cents, so the balance is 352 cents rather than the
    351 a single terminal rounding would produce"

    Design: Difficulty/combinatorial_formula/feed_source_share_round_per_placement_then_sum
    """
    first, second = _two_conversions_of_3715_cents(api)
    move_id = first["move"]["id"]

    feed = fx.read_feed_source(api, first["feed_source"]["id"])
    assert_cents(feed, "accrued_share_cents", 352)
    assert feed["accrued_share_cents"] != 351, (
        "a single terminal rounding of the two raw products would have given 351"
    )

    entries = assert_page(
        api.list_ledger_entries(admin_headers, move_id=move_id),
        total_count=4,
        has_more=False,
    )
    feed_cuts = [
        entry["amount_cents"]
        for entry in entries
        if entry["entry_type"] == LedgerEntryType.FEED_SOURCE_SHARE.value
    ]
    assert feed_cuts == [-176, -176], (
        f"expected two feed-source cuts of -176 each, got {feed_cuts}"
    )
    assert sum(feed_cuts) == -352, (
        f"the journalled cuts must total -352, got {sum(feed_cuts)}"
    )

    accruals = [
        entry["amount_cents"]
        for entry in entries
        if entry["entry_type"] == LedgerEntryType.ACCRUAL.value
    ]
    assert accruals == [1003, 1003], (
        f"expected two accruals of 1003 each, got {accruals}"
    )
    assert second["placement"]["id"] != first["placement"]["id"], (
        "the balance must be the sum over two distinct placements"
    )


# ---------------------------------------------------------------------------
# The deposit: a base times two multipliers read from two different instants
# ---------------------------------------------------------------------------
def _order_with_a_frozen_snapshot_then_a_committed_window(api):
    """Dispatch a credit check on a DRAFT order and only then book the window.

    Dispatch happens while the move is worth 40, and the window commitment that
    follows lifts the live score to 70 without touching the frozen figure.
    """
    bundle = fx.mapped_move(
        api,
        utility_types=[UtilityType.ELECTRIC.value],
        scopes=[ConsentScope.UTILITY_SETUP.value],
    )
    order = bundle["orders_by_type"][UtilityType.ELECTRIC.value]
    handoff = fx.dispatch_credit_check(api, order["id"])
    fx.schedule_order(api, order["id"], requested_service_date="2026-08-20")
    return bundle, order, handoff


def test_05_dispatch_freezes_the_snapshot_at_40_while_the_live_score_climbs_to_70(
    api, ops_headers
):
    """Booking the window after dispatch moves the move but not the snapshot.

    PRD: "the bureau response computes the deposit from that frozen snapshot"

    Design: Difficulty/combinatorial_formula/deposit_uses_snapshot_readiness_evaluation_order
    """
    bundle, order, _handoff = _order_with_a_frozen_snapshot_then_a_committed_window(api)

    order = fx.read_order(api, order["id"])
    assert order["readiness_snapshot"] == 40, (
        f"expected the snapshot frozen at 40, got {order['readiness_snapshot']}"
    )
    assert_order_dimensions(
        order,
        provision_status=ProvisionStatus.SCHEDULED.value,
        credit_status=CreditStatus.PENDING_CHECK.value,
    )
    assert_cents(order, "deposit_amount_cents", 0)

    assert_readiness_breakdown(
        fx.read_readiness(api, bundle["move"]["id"]),
        variant=ReadinessVariant.POST_VERIFICATION.value,
        identity_component=100,
        utility_component=100,
        filing_component=0,
        consent_component=50,
        readiness_score=70,
    )
    assert_move_state(
        fx.read_move(api, bundle["move"]["id"]),
        lifecycle_status=MoveLifecycleStatus.SCHEDULING.value,
        readiness_score=70,
    )
    assert order["readiness_snapshot"] != 70, (
        "the snapshot must not follow the live readiness score after dispatch"
    )


def test_06_the_bureau_answer_prices_the_deposit_off_the_frozen_40_at_18000(
    api, ops_headers, gateway_headers
):
    """A snapshot below 50 buys the 1.20 multiplier even though the move reads 70.

    PRD: "reads the order's frozen `readiness_snapshot` and nothing else: 1.20
    when the snapshot is below 50"

    Design: Difficulty/combinatorial_formula/deposit_uses_snapshot_readiness_evaluation_order
    """
    bundle, order, handoff = _order_with_a_frozen_snapshot_then_a_committed_window(api)

    fx.answer_bureau(api, handoff["id"], 639)

    order = fx.read_order(api, order["id"])
    assert order["readiness_snapshot"] == 40, (
        f"expected the snapshot still 40 at pricing time, got {order['readiness_snapshot']}"
    )
    assert_cents(order, "deposit_amount_cents", 18000)
    assert order["deposit_amount_cents"] != 15000, (
        "pricing off the live score of 70 would have produced 15000 cents"
    )
    assert_order_dimensions(
        order,
        provision_status=ProvisionStatus.SCHEDULED.value,
        credit_status=CreditStatus.DEPOSIT_DUE.value,
    )
    assert_move_state(
        fx.read_move(api, bundle["move"]["id"]),
        lifecycle_status=MoveLifecycleStatus.SCHEDULING.value,
        readiness_score=70,
    )
