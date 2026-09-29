"""Constants, precision and variant selection in the concierge arithmetic.

Each test here pins a literal the PRD fixes rather than a shape: the two
partial-credit constants of duplicate scoring and its single rounding step,
the identity pass bar at both sides of its boundary, the deposit estimate
each `deposit_policy` produces at mapping, the score and readiness
multipliers at a band edge, and the three buckets of the referral waterfall.
"""

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_cents,
    assert_created,
    assert_duplicate_score,
    assert_entry_types,
    assert_move_state,
    assert_ok,
    assert_order_dimensions,
    assert_page,
    ledger_net,
)
from test_helpers.test_users import make_partner_agent_headers
from test_helpers.types import (
    BlockedReason,
    BureauName,
    ConsentScope,
    CreditResult,
    CreditStatus,
    DepositPolicy,
    DuplicateFlag,
    HandoffStatus,
    KbaOutcome,
    LedgerEntryType,
    MoveLifecycleStatus,
    PartnerVertical,
    PlacementStatus,
    ProvisionStatus,
    UtilityType,
    VerificationStatus,
)


def test_01_a_vendor_pass_one_point_below_the_bar_still_fails_identity(
    api, ops_headers, gateway_headers
):
    """A KBA answer of PASSED with 699 resolves to FAILED, not to PASSED.

    PRD: "In every other case the verification moves to `FAILED` — including
    the deliberately counter-intuitive case where `outcome` is `PASSED` but
    `score` falls below 700."

    Design: Corner/calculations/constants_applied_kba_pass_score_699_fails_and_700_passes
    """
    network = fx.build_network(api)
    move = fx.ingest_move(api, network)

    attempt = assert_created(
        api.create_identity_verification(move["id"], fac.kba_attempt_payload(), ops_headers)
    )
    decided = assert_ok(
        api.post_kba_result(
            attempt["id"],
            fac.kba_result_payload(outcome=KbaOutcome.PASSED.value, score=699),
            gateway_headers,
        )
    )

    assert decided["status"] == VerificationStatus.FAILED.value, (
        f"expected FAILED at a score of 699, got {decided['status']}"
    )
    assert decided["kba_score"] == 699, f"expected kba_score 699, got {decided['kba_score']}"

    after = fx.read_move(api, move["id"])
    assert_move_state(
        after,
        lifecycle_status=MoveLifecycleStatus.IDENTITY_FAILED.value,
        readiness_score=0,
    )
    assert after["verified_at"] is None, "a sub-bar score must leave verified_at null"


def test_02_a_vendor_pass_exactly_at_the_bar_verifies_the_move(
    api, ops_headers, gateway_headers
):
    """A KBA answer of PASSED with exactly 700 clears identity.

    PRD: "The passing bar is 700: the verification moves to `PASSED` only when
    `outcome` is `PASSED` **and** `score` is at least 700".

    Design: Corner/calculations/constants_applied_kba_pass_score_699_fails_and_700_passes
    """
    network = fx.build_network(api)
    move = fx.ingest_move(api, network)

    first = assert_created(
        api.create_identity_verification(move["id"], fac.kba_attempt_payload(), ops_headers)
    )
    assert_ok(
        api.post_kba_result(
            first["id"],
            fac.kba_result_payload(outcome=KbaOutcome.PASSED.value, score=699),
            gateway_headers,
        )
    )

    second = assert_created(
        api.create_identity_verification(move["id"], fac.kba_attempt_payload(), ops_headers)
    )
    decided = assert_ok(
        api.post_kba_result(
            second["id"],
            fac.kba_result_payload(outcome=KbaOutcome.PASSED.value, score=700),
            gateway_headers,
        )
    )

    assert decided["status"] == VerificationStatus.PASSED.value, (
        f"expected PASSED at the bar of 700, got {decided['status']}"
    )
    assert decided["attempt_no"] == 2, f"expected attempt_no 2, got {decided['attempt_no']}"
    assert decided["kba_score"] == 700, f"expected kba_score 700, got {decided['kba_score']}"

    after = fx.read_move(api, move["id"])
    assert_move_state(
        after,
        lifecycle_status=MoveLifecycleStatus.VERIFIED.value,
        readiness_score=30,
    )
    assert after["verified_at"] is not None, "a pass at the bar must stamp verified_at"
    assert after["identity_attempt_count"] == 2, (
        f"expected identity_attempt_count 2, got {after['identity_attempt_count']}"
    )


def test_03_a_surname_only_match_and_a_shared_postal_code_earn_partial_credit(
    api, ops_headers
):
    """Duplicate scoring pays 0.60 for a surname and 0.50 for a shared postal code.

    PRD: "The **name component** is 1.00 when the two residents' `full_name`
    values are equal after trimming and case-folding, 0.60 when they are not
    equal but share an identical final token (a surname match), and 0.00
    otherwise."  The address component is "0.50 when they do not but share both
    the same `postal_code` and the same `state_code`".

    Design: Corner/calculations/constants_applied_partial_name_and_partial_address_components
    """
    network = fx.build_network(api)
    relative = fx.create_resident(
        api,
        full_name="Marco Ruiz",
        email=network["resident"]["email"],
        phone_last4="9052",
        date_of_birth="1979-11-02",
        ssn_last4="3318",
    )
    same_postal_other_street = fx.create_address(
        api, fac.origin_address_payload(line1="915 Juniper St", postal_code="30302")
    )

    earlier = fx.ingest_move(api, network, move_date="2026-08-20")
    assert_duplicate_score(earlier, 0.00)
    assert earlier["duplicate_candidate_move_id"] is None, (
        "the first move in an empty store has no candidate"
    )
    assert_move_state(earlier, duplicate_flag=DuplicateFlag.NONE.value)

    later = assert_created(
        api.create_move(
            fac.move_payload(
                relative["id"],
                network["feed_source"]["id"],
                network["origin_address"]["id"],
                same_postal_other_street["id"],
                move_date="2026-08-25",
            ),
            ops_headers,
        )
    )

    assert_duplicate_score(later, 0.71)
    assert later["duplicate_candidate_move_id"] == earlier["id"], (
        "the shared email put the earlier move in the candidate pool"
    )
    assert_move_state(
        later,
        lifecycle_status=MoveLifecycleStatus.INTAKE.value,
        duplicate_flag=DuplicateFlag.NONE.value,
        blocked_reason=BlockedReason.NONE.value,
    )


def test_04_a_raw_duplicate_score_on_a_half_rounds_up_at_the_third_decimal(
    api, ops_headers
):
    """A raw 0.645 becomes 0.65, and the higher-scoring candidate wins the ranking.

    PRD: "Those four products are summed and the sum is rounded **once** to two
    decimal places with round-half-up; that rounded figure is the candidate's
    score.  Candidates are ranked deterministically by score descending, then
    by `created_at` ascending".

    Design: Corner/calculations/precision_duplicate_score_rounds_half_up_at_the_third_decimal
    """
    network = fx.build_network(api)
    relative = fx.create_resident(
        api,
        full_name="Marco Ruiz",
        email=network["resident"]["email"],
        phone_last4="9052",
        date_of_birth="1979-11-02",
        ssn_last4="3318",
    )
    same_postal_other_street = fx.create_address(
        api, fac.origin_address_payload(line1="915 Juniper St", postal_code="30302")
    )
    other_city = fx.create_address(api, fac.third_address_payload())

    fx.ingest_move(api, network, move_date="2026-08-20")
    twin = assert_created(
        api.create_move(
            fac.move_payload(
                relative["id"],
                network["feed_source"]["id"],
                network["origin_address"]["id"],
                same_postal_other_street["id"],
                move_date="2026-08-25",
            ),
            ops_headers,
        )
    )

    scored = assert_created(
        api.create_move(
            fac.move_payload(
                relative["id"],
                network["feed_source"]["id"],
                network["origin_address"]["id"],
                other_city["id"],
                move_date="2026-08-04",
            ),
            ops_headers,
        )
    )

    assert_duplicate_score(scored, 0.65)
    assert scored["duplicate_candidate_move_id"] == twin["id"], (
        "the best-ranked candidate is the one scoring 0.65, not the weaker 0.53"
    )
    assert_move_state(
        scored,
        lifecycle_status=MoveLifecycleStatus.INTAKE.value,
        duplicate_flag=DuplicateFlag.NONE.value,
    )


def _network_with_gas(api):
    """A concierge network whose destination postal code also has a FLAT gas carrier."""
    network = fx.build_network(api)
    gas = fx.create_provider(api, fac.gas_provider_payload())
    gas_territory = fx.create_territory(
        api,
        gas["id"],
        postal_code=network["destination_address"]["postal_code"],
        state_code=network["destination_address"]["state_code"],
    )
    return {**network, "gas_provider": gas, "gas_territory": gas_territory}


def test_05_mapping_estimates_a_credit_scored_carrier_and_a_flat_carrier_apart(
    api, ops_headers
):
    """One mapping run writes a different estimate for each priced deposit policy.

    PRD: "A `CREDIT_SCORE_BASED` provider therefore always estimates 22500
    cents".  A `FLAT` provider instead "multiplies it by the worst score
    multiplier of 1.50, multiplies that by a neutral readiness multiplier of
    1.00" over its own `flat_deposit_cents`.

    Design: Corner/calculations/variant_selection_mapping_writes_one_estimate_per_deposit_policy
    """
    network = _network_with_gas(api)
    bundle = fx.verified_move(
        api, network=network, scopes=[ConsentScope.UTILITY_SETUP.value]
    )

    mapped = fx.run_mapping(
        api,
        bundle["move"]["id"],
        utility_types=[
            UtilityType.ELECTRIC.value,
            UtilityType.GAS.value,
            UtilityType.WATER.value,
        ],
    )
    assert_move_state(mapped, lifecycle_status=MoveLifecycleStatus.SCHEDULING.value)
    assert mapped["mapped_order_count"] == 3, (
        f"expected three mapped orders, got {mapped['mapped_order_count']}"
    )

    electric = fx.order_of_type(api, bundle["move"]["id"], UtilityType.ELECTRIC.value)
    assert_cents(electric, "deposit_estimate_cents", 22500)
    assert_cents(electric, "deposit_amount_cents", 0)
    assert_order_dimensions(
        electric,
        provision_status=ProvisionStatus.DRAFT.value,
        credit_status=CreditStatus.PENDING_CHECK.value,
    )

    gas = fx.order_of_type(api, bundle["move"]["id"], UtilityType.GAS.value)
    assert_cents(gas, "deposit_estimate_cents", 14850)
    assert_cents(gas, "deposit_amount_cents", 0)
    assert_order_dimensions(
        gas,
        provision_status=ProvisionStatus.DRAFT.value,
        credit_status=CreditStatus.PENDING_CHECK.value,
    )


def test_06_a_no_deposit_carrier_estimates_zero_and_skips_the_credit_check(
    api, ops_headers
):
    """A NONE-policy carrier's order carries a zero estimate and needs no bureau.

    PRD: "and nothing at all under a `NONE` policy, which yields an estimate of
    0".  Every freshly mapped order also starts before any freezing point, so
    "`readiness_snapshot` starts null".

    Design: Corner/calculations/variant_selection_mapping_writes_one_estimate_per_deposit_policy
    """
    network = _network_with_gas(api)
    assert network["water_provider"]["deposit_policy"] == DepositPolicy.NONE.value, (
        "the water carrier under test must run a NONE deposit policy"
    )
    bundle = fx.verified_move(
        api, network=network, scopes=[ConsentScope.UTILITY_SETUP.value]
    )

    fx.run_mapping(
        api,
        bundle["move"]["id"],
        utility_types=[
            UtilityType.ELECTRIC.value,
            UtilityType.GAS.value,
            UtilityType.WATER.value,
        ],
    )

    water = fx.order_of_type(api, bundle["move"]["id"], UtilityType.WATER.value)
    assert_cents(water, "deposit_estimate_cents", 0)
    assert_cents(water, "deposit_amount_cents", 0)
    assert_order_dimensions(
        water,
        provision_status=ProvisionStatus.DRAFT.value,
        credit_status=CreditStatus.NOT_REQUIRED.value,
    )

    for order in fx.orders_for_move(api, bundle["move"]["id"]):
        assert order["readiness_snapshot"] is None, (
            f"a freshly mapped {order['utility_type']} order must not carry a "
            f"frozen readiness snapshot, got {order['readiness_snapshot']}"
        )


def _order_awaiting_a_bureau_answer(api):
    """A credit-checked electric order whose frozen readiness snapshot is 40."""
    bundle = fx.mapped_move(api, scopes=[ConsentScope.UTILITY_SETUP.value])
    order = bundle["orders_by_type"][UtilityType.ELECTRIC.value]
    handoff = fx.dispatch_credit_check(
        api, order["id"], bureau=BureauName.TRANSUNION.value
    )
    # PRD: dispatch "writes `readiness_snapshot` on the order, freezing the
    # parent move's `readiness_score` as of that instant" — the frozen figure
    # lives on the order, not on the handoff row.
    dispatched = fx.read_order(api, order["id"])
    assert dispatched["readiness_snapshot"] == 40, (
        f"expected the order to freeze a readiness of 40, got {dispatched['readiness_snapshot']}"
    )
    return bundle, order, handoff


def test_07_a_bureau_score_at_the_deposit_floor_assesses_the_worst_multipliers(
    api, ops_headers, gateway_headers
):
    """A score of exactly 580 buys the 1.50 tier and a weak-readiness 1.20.

    PRD: "The **score multiplier** reads the bureau score: 1.50 for a score from
    580 through 599", while "The **readiness multiplier** reads the order's
    frozen `readiness_snapshot` and nothing else: 1.20 when the snapshot is
    below 50".

    Design: Corner/calculations/tiered_pricing_deposit_at_the_floor_score_uses_the_low_multiplier
    """
    _bundle, order, handoff = _order_awaiting_a_bureau_answer(api)

    answered = assert_ok(
        api.post_bureau_response(
            handoff["id"], fac.bureau_response_payload(580), gateway_headers
        )
    )
    assert answered["handoff_status"] == HandoffStatus.RESPONDED.value, (
        f"expected RESPONDED, got {answered['handoff_status']}"
    )
    assert answered["score"] == 580, f"expected a score of 580, got {answered['score']}"
    assert answered["result"] == CreditResult.DEPOSIT_REQUIRED.value, (
        f"expected DEPOSIT_REQUIRED at the floor score, got {answered['result']}"
    )

    priced = fx.read_order(api, order["id"])
    assert_order_dimensions(priced, credit_status=CreditStatus.DEPOSIT_DUE.value)
    assert_cents(priced, "deposit_amount_cents", 27000)
    assert_cents(priced, "deposit_estimate_cents", 22500)
    assert priced["readiness_snapshot"] == 40, (
        f"the snapshot must stay frozen at 40, got {priced['readiness_snapshot']}"
    )


def test_08_only_the_exact_assessed_deposit_settles_the_credit_dimension(
    api, ops_headers, gateway_headers
):
    """Paying precisely the 27000 assessed at the floor score clears the order.

    PRD: "The request supplies `amount_cents`, which must equal the order's
    `deposit_amount_cents` precisely; neither a partial payment nor an
    over-payment is accepted".

    Design: Corner/calculations/tiered_pricing_deposit_at_the_floor_score_uses_the_low_multiplier
    """
    _bundle, order, handoff = _order_awaiting_a_bureau_answer(api)
    assert_ok(
        api.post_bureau_response(
            handoff["id"], fac.bureau_response_payload(580), gateway_headers
        )
    )

    paid = assert_ok(
        api.pay_deposit(order["id"], fac.deposit_payment_payload(27000), ops_headers)
    )

    assert_order_dimensions(paid, credit_status=CreditStatus.DEPOSIT_PAID.value)
    assert_cents(paid, "deposit_paid_cents", 27000)
    assert_cents(paid, "deposit_amount_cents", 27000)


def _converted_flat_bounty_referral(api):
    """An insurance referral converted on a gross far below the flat bounty."""
    bundle = fx.verified_move(api, scopes=[ConsentScope.PARTNER_MARKETING.value])
    partner = fx.add_insurance_partner(api)
    return fx.converted_referral(
        api, gross_revenue_cents=4000, bundle=bundle, partner=partner
    )


def test_09_a_flat_bounty_commission_ignores_the_reported_gross_revenue(api):
    """A 4000-cent sale still earns the partner's 5000-cent bounty and a 875 cut.

    PRD: "under a `FLAT_BOUNTY` payout model the commission is simply the
    partner's `bounty_cents`, independent of the reported revenue."  The feed
    source's cut is then "the commission multiplied by the originating feed
    source's `referral_revenue_share_pct`, rounded once to whole cents."

    Design: Corner/calculations/waterfall_allocation_flat_bounty_fills_three_buckets_in_order
    """
    converted = _converted_flat_bounty_referral(api)
    placement = converted["placement"]

    assert placement["placement_status"] == PlacementStatus.CONVERTED.value, (
        f"expected CONVERTED, got {placement['placement_status']}"
    )
    assert placement["vertical"] == PartnerVertical.INSURANCE.value, (
        f"the placement must copy the partner's vertical, got {placement['vertical']}"
    )
    assert_cents(placement, "gross_revenue_cents", 4000)
    assert_cents(placement, "attributed_share_cents", 5000)
    assert_cents(placement, "feed_source_share_cents", 875)


def test_10_the_bounty_ledger_leaves_the_platform_its_exact_remainder(api, admin_headers):
    """Two entries journal the bounty and the feed cut, netting the 4125 remainder.

    PRD: Third comes "the **platform remainder**: the commission minus the feed
    source's cut, taken as an exact subtraction and never rounded a second time,
    so the three parts always add back to the commission."

    Design: Corner/calculations/waterfall_allocation_flat_bounty_fills_three_buckets_in_order
    """
    converted = _converted_flat_bounty_referral(api)
    placement = converted["placement"]

    entries = fx.ledger_for_placement(api, placement["id"])
    assert_entry_types(
        entries,
        [LedgerEntryType.ACCRUAL.value, LedgerEntryType.FEED_SOURCE_SHARE.value],
    )
    assert_cents(entries[0], "amount_cents", 5000)
    assert_cents(entries[1], "amount_cents", -875)
    for entry in entries:
        assert entry["move_id"] == converted["move"]["id"], (
            "each entry denormalises the parent move for reporting"
        )
        assert entry["feed_source_id"] == converted["feed_source"]["id"], (
            "each entry denormalises the originating feed source for reporting"
        )

    assert ledger_net(entries) == 4125, (
        f"the platform remainder must be 5000 - 875, got {ledger_net(entries)}"
    )
    feed = fx.read_feed_source(api, converted["feed_source"]["id"])
    assert_cents(feed, "accrued_share_cents", 875)


def _one_converted_and_one_declined_referral(api):
    """A move whose insurance referral converted while its internet one declined."""
    bundle = fx.verified_move(api, scopes=[ConsentScope.PARTNER_MARKETING.value])
    insurance = fx.add_insurance_partner(api)
    converted = fx.converted_referral(
        api, gross_revenue_cents=4000, bundle=bundle, partner=insurance
    )
    paying_placement = converted["placement"]

    internet = fx.add_internet_partner(api)
    second = fx.accepted_referral(api, bundle=converted, partner=internet)
    declined = assert_ok(
        api.decline_placement(
            second["placement"]["id"],
            fac.decline_payload(decline_reason="No fiber drop at the destination unit"),
            make_partner_agent_headers(internet["id"]),
        )
    )
    return {**second, "paying_placement": paying_placement, "declined": declined}


def test_11_a_declined_referral_earns_no_share_and_journals_nothing(api, admin_headers):
    """The decline branch leaves both share fields at 0 and posts no ledger entry.

    PRD: "the owning partner supplies a non-empty `decline_reason`,
    `placement_status` moves to `DECLINED`, and the placement posts no ledger
    entry at all, leaves `attributed_share_cents` at 0, and leaves the feed
    source's `accrued_share_cents` untouched."

    Design: Corner/calculations/input_set_filtering_declined_placement_never_reaches_feed_accrual
    """
    story = _one_converted_and_one_declined_referral(api)
    declined = story["declined"]

    assert declined["placement_status"] == PlacementStatus.DECLINED.value, (
        f"expected DECLINED, got {declined['placement_status']}"
    )
    assert declined["decline_reason"] == "No fiber drop at the destination unit", (
        f"expected the supplied reason, got {declined['decline_reason']!r}"
    )
    assert_cents(declined, "attributed_share_cents", 0)
    assert_cents(declined, "feed_source_share_cents", 0)

    assert fx.ledger_for_placement(api, declined["id"]) == [], (
        "a declined placement must journal nothing at all"
    )


def test_12_the_feed_source_balance_counts_only_the_converted_placement(
    api, admin_headers, ops_headers
):
    """Two placements exist, but only the converted one feeds the running balance.

    PRD: "`accrued_share_cents` on a `FeedSource` is the sum of the
    already-rounded per-placement `feed_source_share_cents` over that source's
    placements in `CONVERTED` or `SETTLED`".

    Design: Corner/calculations/input_set_filtering_declined_placement_never_reaches_feed_accrual
    """
    story = _one_converted_and_one_declined_referral(api)
    feed_source_id = story["feed_source"]["id"]

    assert_page(
        api.list_placements(ops_headers, move_id=story["move"]["id"]), total_count=2
    )
    assert_page(
        api.list_ledger_entries(admin_headers, feed_source_id=feed_source_id),
        total_count=2,
    )

    feed = fx.read_feed_source(api, feed_source_id)
    assert_cents(feed, "accrued_share_cents", 875)
