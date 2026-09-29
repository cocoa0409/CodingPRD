"""Behaviour on both sides of the platform's numeric and temporal boundaries.

Every threshold in this module is exercised twice: once with the input sitting
exactly on the qualifying edge and once with it one step beyond, so an
off-by-one comparison cannot pass both halves.  The edges covered are the
640-point credit band, the 0.80 duplicate-suspicion threshold, the inclusive
end of a partner attribution window and the inclusive end of a territory's
effective interval.
"""

from test_helpers import factories as f, fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents,
    assert_created,
    assert_duplicate_score,
    assert_entry_types,
    assert_error,
    assert_ledger_net,
    assert_move_state,
    assert_ok,
    assert_order_dimensions,
    assert_page,
)
from test_helpers.test_users import make_move_ops_headers, make_partner_agent_headers
from test_helpers.types import (
    BlockedReason,
    ConsentScope,
    CreditResult,
    CreditStatus,
    DuplicateFlag,
    LedgerEntryType,
    MoveLifecycleStatus,
    PlacementStatus,
    ProvisionStatus,
    UtilityType,
    VerificationStatus,
)


def _ingest_move_for(api, network, resident_id, destination_address_id, move_date):
    """Ingest a move naming an explicit resident and destination."""
    payload = f.move_payload(
        resident_id,
        network["feed_source"]["id"],
        network["origin_address"]["id"],
        destination_address_id,
        move_date=move_date,
    )
    return assert_created(api.create_move(payload, make_move_ops_headers()))


# ---------------------------------------------------------------------------
# The 640-point credit band
# ---------------------------------------------------------------------------
def _two_credit_handoffs_frozen_at_forty(api):
    """A move with two CREDIT_SCORE_BASED orders, each with an open handoff.

    Both providers demand a credit decision, so both orders open at
    `PENDING_CHECK`, and both handoffs freeze the same readiness snapshot of
    40 — identity 100, utility 0 of two mapped orders, no filing, and one of
    the two gate consent scopes covered.
    """
    network = fx.build_network(api)
    gas_provider = fx.create_provider(
        api,
        f.electric_provider_payload(
            name="Peachtree Metro Gas", utility_type=UtilityType.GAS.value
        ),
    )
    fx.create_territory(api, gas_provider["id"])
    fx.grant_consents(api, network["resident"]["id"], [ConsentScope.UTILITY_SETUP.value])
    move = fx.ingest_move(api, network, move_date="2026-08-20")
    fx.pass_identity_by_kba(api, move["id"])
    fx.run_mapping(
        api,
        move["id"],
        utility_types=[UtilityType.ELECTRIC.value, UtilityType.GAS.value],
    )
    electric_order = fx.order_of_type(api, move["id"], UtilityType.ELECTRIC.value)
    gas_order = fx.order_of_type(api, move["id"], UtilityType.GAS.value)
    return {
        "network": network,
        "move": move,
        "electric_order": electric_order,
        "gas_order": gas_order,
        "electric_handoff": fx.dispatch_credit_check(api, electric_order["id"]),
        "gas_handoff": fx.dispatch_credit_check(api, gas_order["id"]),
    }


def test_01_bureau_score_of_exactly_640_clears_the_order_with_no_deposit(api):
    """640 is the first score inside the clear band, so no deposit is raised.

    PRD: "A score of 640 or above is a `CLEAR` result. A score from 580 through 639 is a `DEPOSIT_REQUIRED` result."
    PRD: "A `CLEAR` result moves `credit_status` from `PENDING_CHECK` to `CLEARED` and leaves `deposit_amount_cents` at 0"

    Design: Difficulty/boundary_precision_check/credit_score_640_clear_vs_639_deposit_due
    """
    built = _two_credit_handoffs_frozen_at_forty(api)
    assert built["electric_order"]["readiness_snapshot"] is None, (
        "the snapshot is only frozen when the handoff is dispatched"
    )
    assert_cents(built["electric_order"], "deposit_estimate_cents", 22500)

    answered = fx.answer_bureau(api, built["electric_handoff"]["id"], 640)

    assert answered["result"] == CreditResult.CLEAR.value, (
        f"a score of 640 is a CLEAR result, got {answered['result']}"
    )
    order = fx.read_order(api, built["electric_order"]["id"])
    assert_order_dimensions(
        order,
        provision_status=ProvisionStatus.DRAFT.value,
        credit_status=CreditStatus.CLEARED.value,
    )
    assert order["readiness_snapshot"] == 40, (
        f"expected a frozen readiness_snapshot of 40, got {order['readiness_snapshot']}"
    )
    assert_cents(order, "deposit_amount_cents", 0)
    assert_cents(order, "deposit_estimate_cents", 22500)


def test_02_bureau_score_of_639_leaves_a_deposit_of_18000_cents_due(api):
    """639 is the last score inside the deposit band, priced off the frozen 40.

    PRD: "A `DEPOSIT_REQUIRED` result moves `credit_status` to `DEPOSIT_DUE`, writes the computed deposit into `deposit_amount_cents`, and raises the move's open deposit liability by that amount"
    PRD: "1.20 when the snapshot is below 50, 1.00 when the snapshot is from 50 through 79 inclusive, and 0.90 when the snapshot is 80 or above"

    Design: Difficulty/boundary_precision_check/credit_score_640_clear_vs_639_deposit_due
    """
    built = _two_credit_handoffs_frozen_at_forty(api)

    answered = fx.answer_bureau(api, built["gas_handoff"]["id"], 639)

    assert answered["result"] == CreditResult.DEPOSIT_REQUIRED.value, (
        f"a score of 639 is a DEPOSIT_REQUIRED result, got {answered['result']}"
    )
    order = fx.read_order(api, built["gas_order"]["id"])
    assert_order_dimensions(
        order,
        provision_status=ProvisionStatus.DRAFT.value,
        credit_status=CreditStatus.DEPOSIT_DUE.value,
    )
    assert order["readiness_snapshot"] == 40, (
        f"expected a frozen readiness_snapshot of 40, got {order['readiness_snapshot']}"
    )
    assert_cents(order, "deposit_amount_cents", 18000)
    assert_cents(order, "deposit_estimate_cents", 22500)
    assert_cents(order, "deposit_paid_cents", 0)


def test_03_deposit_payment_must_match_the_computed_amount_to_the_cent(api, ops_headers):
    """One cent short of the computed deposit is refused; the exact figure settles it.

    PRD: "The paid `amount_cents` equals the order's `deposit_amount_cents` exactly, with neither partial nor over-payment accepted"
    PRD: "A successful payment writes `deposit_paid_cents` with the paid amount, moves `credit_status` from `DEPOSIT_DUE` to `DEPOSIT_PAID`"

    Design: Difficulty/boundary_precision_check/credit_score_640_clear_vs_639_deposit_due
    """
    built = _two_credit_handoffs_frozen_at_forty(api)
    fx.answer_bureau(api, built["gas_handoff"]["id"], 639)

    short = api.pay_deposit(
        built["gas_order"]["id"], f.deposit_payment_payload(17999), ops_headers
    )

    assert_error(short, ApiErrorId.DEPOSIT_AMOUNT_MISMATCH)
    unpaid = fx.read_order(api, built["gas_order"]["id"])
    assert_order_dimensions(unpaid, credit_status=CreditStatus.DEPOSIT_DUE.value)
    assert_cents(unpaid, "deposit_paid_cents", 0)

    paid = assert_ok(
        api.pay_deposit(
            built["gas_order"]["id"], f.deposit_payment_payload(18000), ops_headers
        )
    )

    assert_order_dimensions(paid, credit_status=CreditStatus.DEPOSIT_PAID.value)
    assert_cents(paid, "deposit_paid_cents", 18000)
    assert_cents(paid, "deposit_amount_cents", 18000)


# ---------------------------------------------------------------------------
# The 0.80 duplicate-suspicion threshold
# ---------------------------------------------------------------------------
def _four_moves_around_the_suspicion_threshold(api):
    """Four moves over two residents and two destinations in the same postal code.

    The clock is advanced between ingestions because a candidate's
    `created_at` must be strictly earlier than the new move's.  The feed sits
    on `TIER_B` with a 30-day dedupe window, so a below-threshold score leaves
    the flag at `NONE` rather than dismissing it.
    """
    network = fx.build_network(api)
    second_resident = fx.create_second_resident(api)
    near_destination = fx.create_destination_address(api, line1="915 Juniper St")

    first_move = fx.ingest_move(api, network, move_date="2026-08-20")
    fx.set_clock(api, "2026-08-01T01:00:00Z")
    shared_address_move = _ingest_move_for(
        api,
        network,
        second_resident["id"],
        network["destination_address"]["id"],
        "2026-08-20",
    )
    fx.set_clock(api, "2026-08-01T02:00:00Z")
    edge_move = _ingest_move_for(
        api, network, network["resident"]["id"], near_destination["id"], "2026-09-04"
    )
    fx.set_clock(api, "2026-08-01T03:00:00Z")
    near_miss_move = _ingest_move_for(
        api, network, second_resident["id"], near_destination["id"], "2026-09-06"
    )
    return {
        "network": network,
        "second_resident": second_resident,
        "first_move": first_move,
        "shared_address_move": shared_address_move,
        "edge_move": edge_move,
        "near_miss_move": near_miss_move,
    }


def test_04_duplicate_score_of_exactly_080_holds_the_move_as_suspected(api, ops_headers):
    """A score landing exactly on 0.80 is suspicious and freezes the move in INTAKE.

    PRD: "The suspicion threshold is 0.80, compared with a greater-than-or-equal test against the already-rounded score"
    PRD: "When the score reaches 0.80 or above, `duplicate_flag` becomes `SUSPECTED` and `blocked_reason` becomes `DUPLICATE_SUSPECTED`, and the move is held in `INTAKE` until a duplicate resolution decides its fate"

    Design: Difficulty/boundary_precision_check/duplicate_score_exactly_080_threshold_vs_079
    """
    built = _four_moves_around_the_suspicion_threshold(api)
    edge = built["edge_move"]

    assert_duplicate_score(edge, 0.80)
    assert_move_state(
        edge,
        lifecycle_status=MoveLifecycleStatus.INTAKE.value,
        duplicate_flag=DuplicateFlag.SUSPECTED.value,
        blocked_reason=BlockedReason.DUPLICATE_SUSPECTED.value,
    )
    assert edge["duplicate_candidate_move_id"] == built["first_move"]["id"], (
        f"expected the candidate pointer to name the earlier move, "
        f"got {edge['duplicate_candidate_move_id']}"
    )

    response = api.create_identity_verification(
        edge["id"], f.kba_attempt_payload(), ops_headers
    )

    assert_error(response, ApiErrorId.DUPLICATE_MOVE_UNRESOLVED)


def test_05_duplicate_score_of_079_leaves_the_move_free_to_progress(api, ops_headers):
    """One hundredth below the threshold is not suspicious and blocks nothing.

    PRD: "a `TIER_A` feed has `duplicate_flag` set to `DISMISSED` automatically, while a `TIER_B` feed leaves `duplicate_flag` at `NONE` so the near-miss stays visible for review"

    Design: Difficulty/boundary_precision_check/duplicate_score_exactly_080_threshold_vs_079
    """
    built = _four_moves_around_the_suspicion_threshold(api)
    near_miss = built["near_miss_move"]

    assert_duplicate_score(near_miss, 0.79)
    assert_move_state(
        near_miss,
        lifecycle_status=MoveLifecycleStatus.INTAKE.value,
        duplicate_flag=DuplicateFlag.NONE.value,
        blocked_reason=BlockedReason.NONE.value,
    )
    assert near_miss["duplicate_candidate_move_id"] == built["shared_address_move"]["id"], (
        f"the best-ranked candidate is the other move of the same resident, "
        f"got {near_miss['duplicate_candidate_move_id']}"
    )

    verification = assert_created(
        api.create_identity_verification(
            near_miss["id"], f.kba_attempt_payload(), ops_headers
        )
    )

    assert verification["status"] == VerificationStatus.PENDING.value, (
        f"the attempt must open as PENDING, got {verification['status']}"
    )


def test_06_below_threshold_score_still_retains_the_near_miss_pointer(api):
    """A 0.40 collision on address and date alone stays visible without blocking.

    PRD: "It writes `duplicate_candidate_move_id` with the winning candidate's identifier, and that foreign key is retained even when the score sits below the threshold, so an operator can always see who the near-miss was"

    Design: Difficulty/boundary_precision_check/duplicate_score_exactly_080_threshold_vs_079
    """
    built = _four_moves_around_the_suspicion_threshold(api)
    shared = built["shared_address_move"]

    assert_duplicate_score(shared, 0.40)
    assert_move_state(
        shared,
        lifecycle_status=MoveLifecycleStatus.INTAKE.value,
        duplicate_flag=DuplicateFlag.NONE.value,
        blocked_reason=BlockedReason.NONE.value,
    )
    assert shared["duplicate_candidate_move_id"] == built["first_move"]["id"], (
        f"expected the retained pointer to name the first move, "
        f"got {shared['duplicate_candidate_move_id']}"
    )
    assert_duplicate_score(built["first_move"], 0.00)
    assert built["first_move"]["duplicate_candidate_move_id"] is None, (
        "the earliest move had nothing to be scored against"
    )


# ---------------------------------------------------------------------------
# The inclusive end of a partner attribution window
# ---------------------------------------------------------------------------
def _two_accepted_referrals(api):
    """Two moves of one resident, each carrying an accepted internet referral.

    The partner anchors attribution on `accepted_at` with a 14-day window, and
    both acceptances land at the startup instant of 2026-08-01T00:00:00Z, so
    the inclusive edge of both windows is 2026-08-15T00:00:00Z.
    """
    network = fx.build_network(api)
    partner = fx.add_internet_partner(api)
    macon = fx.create_address(api, f.third_address_payload())
    fx.grant_consents(
        api, network["resident"]["id"], [ConsentScope.PARTNER_MARKETING.value]
    )
    partner_headers = make_partner_agent_headers(partner["id"])

    accepted = []
    for destination_id, move_date in (
        (network["destination_address"]["id"], "2026-08-20"),
        (macon["id"], "2026-11-01"),
    ):
        move = _ingest_move_for(
            api, network, network["resident"]["id"], destination_id, move_date
        )
        fx.pass_identity_by_kba(api, move["id"])
        current = fx.read_move(api, move["id"])
        placement = fx.place_referral(
            api, current["id"], partner["id"], current["version"]
        )
        accepted.append(
            assert_ok(api.accept_placement(placement["id"], {}, partner_headers))
        )

    return {
        "network": network,
        "partner": partner,
        "partner_headers": partner_headers,
        "edge_placement": accepted[0],
        "late_placement": accepted[1],
    }


def test_07_conversion_at_exactly_the_attribution_edge_is_attributable(api, admin_headers):
    """A conversion landing on the final instant of the window still earns revenue.

    PRD: "the logical clock must be at or before the attribution anchor plus the partner's `attribution_window_days`, the boundary day itself still qualifying"
    PRD: "a gross of 100000 cents against a 0.3000 revenue share yields a provisional commission of 27000 cents; a feed source on a 0.1750 share takes 4725 cents of it; the platform keeps 22275 cents"

    Design: Difficulty/boundary_precision_check/attribution_window_exact_instant_inclusive
    """
    built = _two_accepted_referrals(api)
    placement = built["edge_placement"]
    assert placement["accepted_at"].startswith("2026-08-01T00:00:00"), (
        f"the acceptance anchor must be the startup instant, got {placement['accepted_at']}"
    )
    fx.set_clock(api, "2026-08-15T00:00:00Z")

    converted = assert_ok(
        api.convert_placement(
            placement["id"], f.conversion_payload(100000), built["partner_headers"]
        )
    )

    assert converted["placement_status"] == PlacementStatus.CONVERTED.value, (
        f"expected placement_status CONVERTED, got {converted['placement_status']}"
    )
    assert converted["converted_at"].startswith("2026-08-15T00:00:00"), (
        f"converted_at must be the logical-clock instant, got {converted['converted_at']}"
    )
    assert_cents(converted, "attributed_share_cents", 27000)
    assert_cents(converted, "feed_source_share_cents", 4725)

    entries = fx.ledger_for_placement(api, placement["id"])
    assert_entry_types(
        entries,
        [LedgerEntryType.ACCRUAL.value, LedgerEntryType.FEED_SOURCE_SHARE.value],
    )
    assert_ledger_net(entries, converted)

    feed_source = fx.read_feed_source(api, built["network"]["feed_source"]["id"])
    assert_cents(feed_source, "accrued_share_cents", 4725)


def test_08_conversion_one_second_past_the_attribution_edge_is_refused(api, admin_headers):
    """One second beyond the window earns nothing and posts no ledger row.

    PRD: "a late report is refused with `ERR_ATTRIBUTION_WINDOW_EXPIRED`"
    PRD: "Where a rule speaks of an *instant* (verification expiry, attribution windows, activation windows), the comparison uses the full logical-clock timestamp"

    Design: Difficulty/boundary_precision_check/attribution_window_exact_instant_inclusive
    """
    built = _two_accepted_referrals(api)
    placement = built["late_placement"]
    fx.set_clock(api, "2026-08-15T00:00:01Z")

    response = api.convert_placement(
        placement["id"], f.conversion_payload(100000), built["partner_headers"]
    )

    assert_error(response, ApiErrorId.ATTRIBUTION_WINDOW_EXPIRED)
    after = assert_ok(api.get_placement(placement["id"], admin_headers))
    assert after["placement_status"] == PlacementStatus.ACCEPTED.value, (
        f"the refused placement stays ACCEPTED, got {after['placement_status']}"
    )
    assert after["converted_at"] is None, (
        f"a refused conversion writes no converted_at, got {after['converted_at']}"
    )
    assert_cents(after, "attributed_share_cents", 0)
    assert_cents(after, "feed_source_share_cents", 0)

    assert_page(
        api.list_ledger_entries(admin_headers, placement_id=placement["id"]),
        total_count=0,
    )
    feed_source = fx.read_feed_source(api, built["network"]["feed_source"]["id"])
    assert_cents(feed_source, "accrued_share_cents", 0)


# ---------------------------------------------------------------------------
# The inclusive end of a territory's effective interval
# ---------------------------------------------------------------------------
def _two_moves_against_a_closing_territory(api, ops_headers):
    """One water territory closing on 2026-08-20, and two moves straddling it.

    The network is built by hand so the closing row is the only coverage that
    exists for the Savannah postal code: one move lands exactly on the row's
    inclusive `effective_to`, the other one day later.
    """
    fx.reset_clock(api)
    feed_source = fx.create_feed_source(api)
    first_resident = fx.create_resident(api)
    second_resident = fx.create_second_resident(api)
    origin = fx.create_origin_address(api)
    inside_address = fx.create_address(
        api,
        f.destination_address_payload(
            line1="12 Bay St", unit="2A", city="Savannah", postal_code="31401"
        ),
    )
    outside_address = fx.create_address(
        api,
        f.destination_address_payload(
            line1="480 Drayton Rd", unit="5C", city="Savannah", postal_code="31401"
        ),
    )
    provider = fx.create_provider(api, f.water_provider_payload())
    territory = fx.create_territory(
        api, provider["id"], postal_code="31401", effective_to="2026-08-20"
    )
    fx.grant_consents(api, first_resident["id"], [ConsentScope.UTILITY_SETUP.value])
    fx.grant_consents(api, second_resident["id"], [ConsentScope.UTILITY_SETUP.value])

    network = {"feed_source": feed_source, "origin_address": origin}
    inside_move = _ingest_move_for(
        api, network, first_resident["id"], inside_address["id"], "2026-08-20"
    )
    outside_move = _ingest_move_for(
        api, network, second_resident["id"], outside_address["id"], "2026-08-21"
    )
    fx.pass_identity_by_kba(api, inside_move["id"])
    fx.pass_identity_by_kba(api, outside_move["id"])
    return {
        "provider": provider,
        "territory": territory,
        "inside_address": inside_address,
        "inside_move": inside_move,
        "outside_move": outside_move,
    }


def test_09_mapping_succeeds_on_the_inclusive_end_of_the_effective_interval(api, ops_headers):
    """A move dated exactly on `effective_to` still finds the territory eligible.

    PRD: "the move's `move_date` falls inside the row's closed effective interval — at or after `effective_from`, and at or before `effective_to` when that end date is present"
    PRD: "Success drives `lifecycle_status` from `VERIFIED` to `SCHEDULING`"

    Design: Difficulty/boundary_precision_check/provider_mapping_empty_candidate_pool_boundary
    """
    built = _two_moves_against_a_closing_territory(api, ops_headers)

    mapped = assert_ok(
        api.run_provider_mapping(
            built["inside_move"]["id"],
            f.mapping_payload([UtilityType.WATER.value]),
            ops_headers,
        )
    )

    assert_move_state(
        mapped,
        lifecycle_status=MoveLifecycleStatus.SCHEDULING.value,
        readiness_score=40,
    )
    assert mapped["mapped_order_count"] == 1, (
        f"expected mapped_order_count 1, got {mapped['mapped_order_count']}"
    )
    rows = assert_page(
        api.list_utility_orders(ops_headers, move_id=built["inside_move"]["id"]),
        total_count=1,
    )
    order = rows[0]
    assert order["provider_id"] == built["provider"]["id"], (
        f"expected the water provider to win, got {order['provider_id']}"
    )
    assert order["territory_id"] == built["territory"]["id"], (
        f"the winning territory row must be pinned, got {order['territory_id']}"
    )
    assert order["service_address_id"] == built["inside_address"]["id"], (
        "a START order serves the destination address"
    )
    assert_order_dimensions(
        order,
        provision_status=ProvisionStatus.DRAFT.value,
        credit_status=CreditStatus.NOT_REQUIRED.value,
    )


def test_10_mapping_one_day_past_the_effective_end_finds_no_coverage(api, ops_headers):
    """A move dated one day past `effective_to` empties the candidate pool.

    PRD: "When **no** requested utility type has any eligible row at all, mapping is refused with `ERR_NO_PROVIDER_COVERAGE`"

    Design: Difficulty/boundary_precision_check/provider_mapping_empty_candidate_pool_boundary
    """
    built = _two_moves_against_a_closing_territory(api, ops_headers)

    response = api.run_provider_mapping(
        built["outside_move"]["id"],
        f.mapping_payload([UtilityType.WATER.value]),
        ops_headers,
    )

    assert_error(response, ApiErrorId.NO_PROVIDER_COVERAGE)
    move = fx.read_move(api, built["outside_move"]["id"])
    assert_move_state(
        move,
        lifecycle_status=MoveLifecycleStatus.VERIFIED.value,
        readiness_score=40,
    )
    assert move["mapped_order_count"] == 0, (
        f"a refused mapping creates nothing, got mapped_order_count {move['mapped_order_count']}"
    )
    assert_page(
        api.list_utility_orders(ops_headers, move_id=built["outside_move"]["id"]),
        total_count=0,
    )
