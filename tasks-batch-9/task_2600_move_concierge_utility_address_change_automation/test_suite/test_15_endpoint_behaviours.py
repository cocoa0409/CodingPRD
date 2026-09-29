"""Endpoint behaviour: round trips, junction resolution, checkpoints and listings.

Each test here builds its own world through declared endpoints and then
exercises one endpoint family the way the PRD describes it: a reference-data
write read back unchanged, a many-to-many territory resolution whose two
ordering clauses disagree, an operations checkpoint whose only job is to
notice that the logical clock has moved, a computed read that must mutate
nothing, an action endpoint that is refused and then becomes available, and a
collection endpoint whose window bookkeeping has to describe the filtered set
rather than the table.  The logical clock is pinned explicitly wherever a
temporal rule decides the outcome.
"""

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents,
    assert_created,
    assert_error,
    assert_move_state,
    assert_ok,
    assert_page,
    assert_pct_field,
    assert_readiness_breakdown,
    assert_unchanged,
    assert_versioned_resource,
    assert_window_released,
)
from test_helpers.constants import CLOCK_STARTUP_DEFAULT
from test_helpers.test_users import make_provider_agent_headers
from test_helpers.types import (
    AttributionBasis,
    BlockedReason,
    ConsentGate,
    ConsentScope,
    ConsentSourceChannel,
    ConsentState,
    CreditStatus,
    MoveLifecycleStatus,
    PartnerStatus,
    PartnerVertical,
    PayoutModel,
    ProvisionStatus,
    ReadinessVariant,
    UtilityType,
)


# ---------------------------------------------------------------------------
# Referral partner create-and-read round trip
# ---------------------------------------------------------------------------
def test_01_registering_a_rev_share_partner_takes_both_sibling_defaults(api, admin_headers):
    """A REV_SHARE_PCT partner opens ACTIVE at version 1 with its bounty field still 0.

    PRD: "`bounty_cents` defaults to 0 and must not be negative"
    PRD: "Partners begin at `partner_status` `ACTIVE`; an admin may move them to
    `PAUSED` and back."

    Design: Corner/endpoints/standard_crud_referral_partner_create_and_read_round_trip
    """
    fixtures.set_clock(api, CLOCK_STARTUP_DEFAULT)

    response = api.create_referral_partner(factories.internet_partner_payload(), admin_headers)
    partner = assert_created(response)

    assert partner["partner_status"] == PartnerStatus.ACTIVE.value, (
        f"a newly registered partner must open ACTIVE, got {partner['partner_status']}"
    )
    assert_cents(partner, "bounty_cents", 0)
    assert_versioned_resource(partner, expected_version=1)


def test_02_reading_the_partner_back_preserves_its_four_decimal_revenue_share(api, admin_headers, ops_headers):
    """The GET returns the same row with rev_share_pct still carried at four decimal places.

    PRD: "Percentage-shaped configuration fields — `referral_revenue_share_pct`
    on a feed source and `rev_share_pct` on a partner — are decimal fractions
    carried at 4 decimal places, so a thirty-percent revenue share is stored as
    0.3000."
    PRD: "an integer that starts at 1 on creation and increments by one on every
    mutation of that row"

    Design: Corner/endpoints/standard_crud_referral_partner_create_and_read_round_trip
    """
    fixtures.set_clock(api, CLOCK_STARTUP_DEFAULT)
    written = assert_created(
        api.create_referral_partner(factories.internet_partner_payload(), admin_headers)
    )

    read_back = assert_ok(api.get_referral_partner(written["id"], ops_headers))

    assert read_back["id"] == written["id"], "the read returned a different row"
    assert read_back["name"] == "Skyline Fiber", f"unexpected name {read_back['name']}"
    assert read_back["vertical"] == PartnerVertical.INTERNET.value, (
        f"unexpected vertical {read_back['vertical']}"
    )
    assert read_back["payout_model"] == PayoutModel.REV_SHARE_PCT.value, (
        f"unexpected payout_model {read_back['payout_model']}"
    )
    assert_pct_field(read_back, "rev_share_pct", 0.3)
    assert read_back["attribution_window_days"] == 14, (
        f"unexpected attribution_window_days {read_back['attribution_window_days']}"
    )
    assert read_back["attribution_basis"] == AttributionBasis.PLACEMENT_ACCEPTANCE.value, (
        f"unexpected attribution_basis {read_back['attribution_basis']}"
    )
    assert read_back["monthly_placement_cap"] == 5, (
        f"unexpected monthly_placement_cap {read_back['monthly_placement_cap']}"
    )
    assert_unchanged(written, read_back)
    assert_versioned_resource(read_back, expected_version=1)


# ---------------------------------------------------------------------------
# Territory resolution: the default carrier outranks the better rank
# ---------------------------------------------------------------------------
def _two_electric_carriers(api):
    """A verified move on 30302 served by a non-default rank 1 and a default rank 5."""
    fixtures.set_clock(api, CLOCK_STARTUP_DEFAULT)
    feed = fixtures.create_feed_source(api)
    resident = fixtures.create_resident(api)
    origin = fixtures.create_origin_address(api)
    destination = fixtures.create_destination_address(api)

    ranked = fixtures.create_provider(api, factories.electric_provider_payload())
    default_carrier = fixtures.create_provider(
        api, factories.alternate_electric_provider_payload()
    )
    ranked_territory = fixtures.create_territory(
        api, ranked["id"], priority_rank=1, is_default_carrier=False
    )
    default_territory = fixtures.create_territory(
        api, default_carrier["id"], priority_rank=5, is_default_carrier=True
    )

    fixtures.grant_consent(api, resident["id"], ConsentScope.UTILITY_SETUP.value, 1)
    network = {
        "feed_source": feed,
        "resident": resident,
        "origin_address": origin,
        "destination_address": destination,
    }
    move = fixtures.ingest_move(api, network)
    fixtures.pass_identity_by_kba(api, move["id"])
    return {
        "resident": resident,
        "move": move,
        "ranked_provider": ranked,
        "default_provider": default_carrier,
        "ranked_territory": ranked_territory,
        "default_territory": default_territory,
    }


def test_03_territory_listing_combines_the_provider_and_default_carrier_filters(api, ops_headers):
    """Two rows cover 30302, and narrowing by provider and default-carrier flag leaves one.

    PRD: "Filter parameters on list endpoints are combined conjunctively"
    PRD: "Territory rows are listable and filterable by `provider_id`,
    `postal_code`, `state_code` and `is_default_carrier`."

    Design: Corner/endpoints/cross_reference_link_mapping_prefers_the_default_carrier_over_the_better_rank
    """
    world = _two_electric_carriers(api)

    covering = assert_page(
        api.list_territories(ops_headers, postal_code="30302", limit=10, offset=0),
        total_count=2,
        has_more=False,
        limit=10,
        offset=0,
    )
    provider_ids = {row["provider_id"] for row in covering}
    assert provider_ids == {
        world["ranked_provider"]["id"],
        world["default_provider"]["id"],
    }, f"both carriers must appear on 30302, got {provider_ids}"

    narrowed = assert_page(
        api.list_territories(
            ops_headers,
            provider_id=world["ranked_provider"]["id"],
            is_default_carrier="false",
            limit=10,
            offset=0,
        ),
        total_count=1,
        has_more=False,
    )
    assert narrowed[0]["id"] == world["ranked_territory"]["id"], (
        "the two filters must combine to the single non-default row of that provider"
    )


def test_04_mapping_lets_the_default_carrier_beat_the_lower_priority_rank(api, ops_headers):
    """The winning order names the default carrier at rank 5, not the non-default at rank 1.

    PRD: "Among the eligible rows the winner is chosen by four ordered keys:
    default-carrier rows first (`is_default_carrier` true ahead of false), then
    the lowest `priority_rank`, then the latest `effective_from`, then the
    earliest `created_at`."
    PRD: "the winning territory row's identifier as `territory_id` (pinned
    purely for audit)"

    Design: Corner/endpoints/cross_reference_link_mapping_prefers_the_default_carrier_over_the_better_rank
    """
    world = _two_electric_carriers(api)

    fixtures.run_mapping(api, world["move"]["id"], utility_types=[UtilityType.ELECTRIC.value])
    order = fixtures.order_of_type(api, world["move"]["id"], UtilityType.ELECTRIC.value)

    assert order["provider_id"] == world["default_provider"]["id"], (
        "is_default_carrier true must outrank the lower priority_rank"
    )
    assert order["territory_id"] == world["default_territory"]["id"], (
        f"territory_id must pin the winning row, got {order['territory_id']}"
    )


def test_05_the_order_inherits_the_winning_carriers_credit_terms(api, ops_headers):
    """Because the winner needs no credit check, the order opens NOT_REQUIRED with a zero estimate.

    PRD: "`PENDING_CHECK` when that provider has `credit_check_required` true,
    and `NOT_REQUIRED` when it does not"
    PRD: "nothing at all under a `NONE` policy, which yields an estimate of 0"

    Design: Corner/endpoints/cross_reference_link_mapping_prefers_the_default_carrier_over_the_better_rank
    """
    world = _two_electric_carriers(api)

    fixtures.run_mapping(api, world["move"]["id"], utility_types=[UtilityType.ELECTRIC.value])
    order = fixtures.order_of_type(api, world["move"]["id"], UtilityType.ELECTRIC.value)

    assert order["credit_status"] == CreditStatus.NOT_REQUIRED.value, (
        "the credit posture must come from the winning provider, not the better-ranked one"
    )
    assert_cents(order, "deposit_estimate_cents", 0)


# ---------------------------------------------------------------------------
# The consent-evaluation checkpoint expires a dated consent
# ---------------------------------------------------------------------------
def _move_with_dated_consent(api):
    """A SCHEDULING move whose only consent lapses at 2026-08-05T00:00:00Z."""
    network = fixtures.build_network(api)
    consent = fixtures.grant_consent(
        api,
        network["resident"]["id"],
        ConsentScope.UTILITY_SETUP.value,
        1,
        source_channel=ConsentSourceChannel.WEB_PORTAL.value,
        expires_at="2026-08-05T00:00:00Z",
    )
    move = fixtures.ingest_move(api, network)
    fixtures.pass_identity_by_kba(api, move["id"])
    fixtures.run_mapping(api, move["id"], utility_types=[UtilityType.WATER.value])
    order = fixtures.order_of_type(api, move["id"], UtilityType.WATER.value)
    return {
        "network": network,
        "consent": consent,
        "move": fixtures.read_move(api, move["id"]),
        "order": order,
    }


def test_06_advancing_the_clock_alone_does_not_expire_the_consent(api, ops_headers):
    """Time passing is not an event: until the checkpoint runs the move is untouched.

    PRD: "the checkpoint moves every `GRANTED` consent record of that resident
    whose `expires_at` is non-null and strictly behind the logical clock to
    `EXPIRED`"
    PRD: "Setting the clock mutates no entity — it changes only the instant
    against which subsequent requests evaluate their temporal rules."

    Design: Corner/endpoints/action_endpoint_consent_evaluation_expires_a_dated_consent_and_blocks_the_move
    """
    world = _move_with_dated_consent(api)
    assert_move_state(
        world["move"],
        lifecycle_status=MoveLifecycleStatus.SCHEDULING.value,
        consent_gate=ConsentGate.OPEN.value,
        blocked_reason=BlockedReason.NONE.value,
        readiness_score=40,
    )

    fixtures.set_clock(api, "2026-08-06T00:00:00Z")

    still_open = fixtures.read_move(api, world["move"]["id"])
    assert_move_state(
        still_open,
        lifecycle_status=MoveLifecycleStatus.SCHEDULING.value,
        consent_gate=ConsentGate.OPEN.value,
        blocked_reason=BlockedReason.NONE.value,
        readiness_score=40,
    )
    assert_unchanged(world["move"], still_open)


def test_07_the_checkpoint_blocks_the_move_and_suspends_its_order(api, admin_headers):
    """One call past the expiry parks the move and fires the revocation cascade.

    PRD: "firing exactly the same cascade hops as a revocation with
    `blocked_reason` set to `CONSENT_REVOKED`"
    PRD: "moves every service order of those moves whose `provision_status` is
    `DRAFT`, `SCHEDULED` or `ACTIVE_SERVICE` to `SUSPENDED`"

    Design: Corner/endpoints/action_endpoint_consent_evaluation_expires_a_dated_consent_and_blocks_the_move
    """
    world = _move_with_dated_consent(api)
    fixtures.set_clock(api, "2026-08-06T00:00:00Z")

    evaluated = assert_ok(api.evaluate_consents(world["move"]["id"], {}, admin_headers))

    assert_move_state(
        evaluated,
        lifecycle_status=MoveLifecycleStatus.ATTENTION_REQUIRED.value,
        consent_gate=ConsentGate.BLOCKED.value,
        blocked_reason=BlockedReason.CONSENT_REVOKED.value,
        readiness_score=30,
    )
    suspended = fixtures.read_order(api, world["order"]["id"])
    assert suspended["provision_status"] == ProvisionStatus.SUSPENDED.value, (
        f"the DRAFT order must be suspended, got {suspended['provision_status']}"
    )
    assert_window_released(suspended)


def test_08_an_expired_consent_is_not_recorded_as_a_revocation(api, admin_headers):
    """The lapsed record lands in EXPIRED with the revocation columns still null.

    PRD: "The record is created in `state` `GRANTED` with `granted_at` set to
    the current instant and with `revoked_at` and `revocation_reason` both null."
    PRD: "whose `expires_at` is non-null and strictly behind the logical clock
    to `EXPIRED`"

    Design: Corner/endpoints/action_endpoint_consent_evaluation_expires_a_dated_consent_and_blocks_the_move
    """
    world = _move_with_dated_consent(api)
    fixtures.set_clock(api, "2026-08-06T00:00:00Z")

    assert_ok(api.evaluate_consents(world["move"]["id"], {}, admin_headers))

    consent = assert_ok(api.get_consent_record(world["consent"]["id"], admin_headers))
    assert consent["state"] == ConsentState.EXPIRED.value, (
        f"expected the record to be EXPIRED, got {consent['state']}"
    )
    assert consent["revoked_at"] is None, (
        "an expiry is not a revocation, so revoked_at must stay null"
    )
    assert consent["revocation_reason"] is None, (
        "an expiry is not a revocation, so revocation_reason must stay null"
    )


# ---------------------------------------------------------------------------
# The readiness breakdown is a pure projection
# ---------------------------------------------------------------------------
def _scheduling_move_on_one_consent(api):
    """A SCHEDULING move holding UTILITY_SETUP only, with one DRAFT water order."""
    network = fixtures.build_network(api)
    fixtures.grant_consent(api, network["resident"]["id"], ConsentScope.UTILITY_SETUP.value, 1)
    move = fixtures.ingest_move(api, network)
    fixtures.pass_identity_by_kba(api, move["id"])
    fixtures.run_mapping(api, move["id"], utility_types=[UtilityType.WATER.value])
    return fixtures.read_move(api, move["id"])


def test_09_the_breakdown_exposes_every_weighted_component(api, ops_headers):
    """The read returns all four components and the score they combine into.

    PRD: "It returns the `move_id`, the `variant` that was used, all four of
    `identity_component`, `utility_component`, `filing_component` and
    `consent_component`, and the resulting `readiness_score`."
    PRD: "it applies all four weights — identity 0.30, utility 0.30, filing
    0.20, consent 0.20 — with no renormalisation"
    PRD: "50 when exactly one of those two scopes is covered"

    Design: Corner/endpoints/computed_read_readiness_breakdown_is_a_pure_projection
    """
    move = _scheduling_move_on_one_consent(api)

    breakdown = assert_ok(api.get_move_readiness(move["id"], ops_headers))

    assert breakdown["move_id"] == move["id"], (
        f"the breakdown must name the move it describes, got {breakdown['move_id']}"
    )
    assert_readiness_breakdown(
        breakdown,
        variant=ReadinessVariant.POST_VERIFICATION.value,
        identity_component=100,
        utility_component=0,
        filing_component=0,
        consent_component=50,
        readiness_score=40,
    )
    assert breakdown["readiness_score"] == move["readiness_score"], (
        "the projection must agree with the score already stored on the move"
    )


def test_10_reading_the_breakdown_twice_mutates_nothing(api, ops_headers, admin_headers):
    """Two reads by two roles return the same numbers and leave the move at its version.

    PRD: "Computed read of the move readiness score and its four components;
    variant defaults to the one implied by lifecycle_status"
    PRD: "an integer that starts at 1 on creation and increments by one on every
    mutation of that row"

    Design: Corner/endpoints/computed_read_readiness_breakdown_is_a_pure_projection
    """
    move = _scheduling_move_on_one_consent(api)

    first = assert_ok(api.get_move_readiness(move["id"], ops_headers))
    second = assert_ok(api.get_move_readiness(move["id"], admin_headers))

    assert first == second, f"the projection is not stable across reads: {first} vs {second}"

    after = fixtures.read_move(api, move["id"])
    assert_unchanged(move, after)
    assert_move_state(
        after,
        lifecycle_status=MoveLifecycleStatus.SCHEDULING.value,
        readiness_score=40,
    )


# ---------------------------------------------------------------------------
# Attention clearance is conditional on a replacement order
# ---------------------------------------------------------------------------
def _move_parked_by_a_failed_water_order(api):
    """A move in ATTENTION_REQUIRED whose only water order is PROVISION_FAILED."""
    bundle = fixtures.mapped_move(api, utility_types=[UtilityType.WATER.value])
    order = bundle["orders_by_type"][UtilityType.WATER.value]
    fixtures.schedule_order(api, order["id"])
    failed = assert_ok(
        api.report_provision_failure(
            order["id"],
            factories.provision_failure_payload(),
            make_provider_agent_headers(order["provider_id"]),
        )
    )
    return {
        "network": bundle,
        "move": fixtures.read_move(api, bundle["move"]["id"]),
        "failed_order": failed,
    }


def test_11_clearance_is_refused_while_the_failed_order_has_no_replacement(api, ops_headers):
    """The clearance call is rejected and the move stays parked on the same reason.

    PRD: "A clearance attempted while a failed or declined order still has no
    replacement is refused with `ERR_UNRESOLVED_PROVISION_FAILURE`."

    Design: Corner/endpoints/conditional_action_attention_clearance_requires_a_replacement_order
    """
    world = _move_parked_by_a_failed_water_order(api)

    response = api.clear_attention(
        world["move"]["id"], factories.clearance_payload(), ops_headers
    )
    assert_error(response, ApiErrorId.UNRESOLVED_PROVISION_FAILURE, expected_status=409)

    parked = fixtures.read_move(api, world["move"]["id"])
    assert_move_state(
        parked,
        lifecycle_status=MoveLifecycleStatus.ATTENTION_REQUIRED.value,
        blocked_reason=BlockedReason.PROVISION_FAILED.value,
    )
    assert_unchanged(world["move"], parked)


def test_12_remapping_the_utility_raises_a_replacement_without_unparking_the_move(api, ops_headers):
    """A second mapping run leaves the move parked but adds a fresh DRAFT order.

    PRD: "running it while the move is parked in `ATTENTION_REQUIRED` leaves it
    in `ATTENTION_REQUIRED` (a second self-loop)"
    PRD: "An order that is `CANCELLED`, `CLOSED`, `NOT_APPLICABLE` or
    `PROVISION_FAILED` does **not** block a replacement"

    Design: Corner/endpoints/conditional_action_attention_clearance_requires_a_replacement_order
    """
    world = _move_parked_by_a_failed_water_order(api)

    remapped = fixtures.run_mapping(
        api, world["move"]["id"], utility_types=[UtilityType.WATER.value]
    )
    assert_move_state(
        remapped,
        lifecycle_status=MoveLifecycleStatus.ATTENTION_REQUIRED.value,
        blocked_reason=BlockedReason.PROVISION_FAILED.value,
    )

    orders = fixtures.orders_for_move(api, world["move"]["id"])
    assert len(orders) == 2, f"a replacement order must have been raised, got {len(orders)}"
    statuses = sorted(order["provision_status"] for order in orders)
    assert statuses == [
        ProvisionStatus.DRAFT.value,
        ProvisionStatus.PROVISION_FAILED.value,
    ], f"expected one DRAFT replacement beside the failed order, got {statuses}"


def test_13_the_same_clearance_body_succeeds_once_the_replacement_exists(api, ops_headers):
    """The previously refused call now returns the move to SCHEDULING on NONE.

    PRD: "Success returns `lifecycle_status` to `SCHEDULING`, resets
    `blocked_reason` to `NONE`, and recomputes `readiness_score`."

    Design: Corner/endpoints/conditional_action_attention_clearance_requires_a_replacement_order
    """
    world = _move_parked_by_a_failed_water_order(api)
    payload = factories.clearance_payload()
    assert_error(
        api.clear_attention(world["move"]["id"], payload, ops_headers),
        ApiErrorId.UNRESOLVED_PROVISION_FAILURE,
    )
    fixtures.run_mapping(api, world["move"]["id"], utility_types=[UtilityType.WATER.value])

    cleared = assert_ok(api.clear_attention(world["move"]["id"], payload, ops_headers))

    assert_move_state(
        cleared,
        lifecycle_status=MoveLifecycleStatus.SCHEDULING.value,
        blocked_reason=BlockedReason.NONE.value,
    )
    failed_still = fixtures.read_order(api, world["failed_order"]["id"])
    assert failed_still["provision_status"] == ProvisionStatus.PROVISION_FAILED.value, (
        "clearing attention must not rewrite the failed order"
    )


# ---------------------------------------------------------------------------
# Listing service orders: filters plus the page window
# ---------------------------------------------------------------------------
def _two_orders_one_scheduled(api):
    """A move with a DRAFT electric order on PENDING_CHECK and a SCHEDULED water order."""
    bundle = fixtures.mapped_move(api)
    water = bundle["orders_by_type"][UtilityType.WATER.value]
    fixtures.schedule_order(api, water["id"])
    return {
        "move": bundle["move"],
        "electric": bundle["orders_by_type"][UtilityType.ELECTRIC.value],
        "water": water,
    }


def test_14_each_status_filter_selects_the_one_order_that_matches(api, ops_headers):
    """Filtering on either state dimension narrows the move's two orders to one.

    PRD: "are listable with filters on `move_id`, `provider_id`,
    `service_address_id`, `territory_id`, `provision_status`, `credit_status`,
    `order_kind` and `utility_type`"
    PRD: "Filter parameters on list endpoints are combined conjunctively"

    Design: Corner/endpoints/listing_utility_orders_combines_status_filter_with_pagination
    """
    world = _two_orders_one_scheduled(api)

    drafts = assert_page(
        api.list_utility_orders(
            ops_headers,
            move_id=world["move"]["id"],
            provision_status=ProvisionStatus.DRAFT.value,
        ),
        total_count=1,
        has_more=False,
    )
    assert drafts[0]["id"] == world["electric"]["id"], (
        "only the unscheduled electric order is still DRAFT"
    )

    no_credit = assert_page(
        api.list_utility_orders(
            ops_headers,
            move_id=world["move"]["id"],
            credit_status=CreditStatus.NOT_REQUIRED.value,
        ),
        total_count=1,
        has_more=False,
    )
    assert no_credit[0]["id"] == world["water"]["id"], (
        "only the water order sits on a provider needing no credit check"
    )


def test_15_a_one_row_window_reports_the_unfiltered_total_and_has_more(api, ops_headers):
    """Two successive windows of one row each are disjoint and both report total_count 2.

    PRD: "`total_count` (the number of rows matching the filters before the page
    window is applied) and `has_more` (true when rows remain after the current
    window)"

    Design: Corner/endpoints/listing_utility_orders_combines_status_filter_with_pagination
    """
    world = _two_orders_one_scheduled(api)

    first = assert_page(
        api.list_utility_orders(ops_headers, move_id=world["move"]["id"], limit=1, offset=0),
        total_count=2,
        has_more=True,
        limit=1,
        offset=0,
    )
    second = assert_page(
        api.list_utility_orders(ops_headers, move_id=world["move"]["id"], limit=1, offset=1),
        total_count=2,
        has_more=False,
        limit=1,
        offset=1,
    )

    assert len(first) == 1 and len(second) == 1, (
        f"each window must hold one row, got {len(first)} and {len(second)}"
    )
    assert first[0]["id"] != second[0]["id"], "the two windows returned the same row"
    assert {first[0]["id"], second[0]["id"]} == {
        world["electric"]["id"],
        world["water"]["id"],
    }, "the two windows together must cover both orders"


def test_16_the_status_filter_narrows_the_total_the_window_reports(api, ops_headers):
    """A filtered one-row window reports the filtered total, and an empty match is still a 200.

    PRD: "`total_count` (the number of rows matching the filters before the page
    window is applied)"
    PRD: "Filter parameters on list endpoints are combined conjunctively"

    Design: Corner/endpoints/listing_utility_orders_combines_status_filter_with_pagination
    """
    world = _two_orders_one_scheduled(api)

    scheduled = assert_page(
        api.list_utility_orders(
            ops_headers,
            move_id=world["move"]["id"],
            provision_status=ProvisionStatus.SCHEDULED.value,
            limit=1,
            offset=0,
        ),
        total_count=1,
        has_more=False,
        limit=1,
        offset=0,
    )
    assert scheduled[0]["id"] == world["water"]["id"], (
        "the filtered total must count only the scheduled order"
    )

    empty = assert_page(
        api.list_utility_orders(
            ops_headers,
            move_id=world["move"]["id"],
            provision_status=ProvisionStatus.CANCELLED.value,
        ),
        total_count=0,
        has_more=False,
    )
    assert empty == [], f"an unmatched filter must return an empty page, got {empty}"
