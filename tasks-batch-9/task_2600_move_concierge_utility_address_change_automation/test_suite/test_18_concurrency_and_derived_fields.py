"""Optimistic concurrency on two parents, and one derived field reconciled to its ledger.

Three write paths in this API demand the caller quote the version it read:
consent creation quotes the resident, and referral placement and duplicate
resolution quote the move.  Each is checked the same way — a stale quote is
refused with the precise 412, the refused write leaves no row behind, and the
retry with the freshly read version goes through.  Counting is checked
alongside it: a version advances exactly once per successful write and never
on a read.  The last pair reconciles a feed source's accrued share against
the signed ledger entries that produced it, across a conversion of two
placements and the reversal of one.
"""

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents,
    assert_created,
    assert_duplicate_score,
    assert_error,
    assert_move_state,
    assert_ok,
    assert_page,
    assert_unchanged,
    assert_version_bumped,
    assert_versioned_resource,
)
from test_helpers.test_users import make_partner_agent_headers
from test_helpers.types import (
    BlockedReason,
    ConsentScope,
    ConsentState,
    DuplicateFlag,
    DuplicateResolution,
    LedgerEntryType,
    MoveLifecycleStatus,
    PartnerVertical,
    PlacementStatus,
    UtilityType,
)


# ---------------------------------------------------------------------------
# Consent creation quotes the resident version
# ---------------------------------------------------------------------------
def test_01_a_consent_quoting_the_superseded_resident_version_is_refused(api, ops_headers, admin_headers):
    """A marketing patch moves the resident on, and the pre-patch quote is rejected.

    PRD: "Recording a data-sharing consent for a resident requires a non-optional
    `expected_resident_version` field in the request body, carrying the client's
    last observed `version` of that `Resident`."
    PRD: "If that value does not match the resident's current `version`, the
    create is rejected with `ERR_STALE_RESIDENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_consent_creation_rejects_a_stale_resident_version
    """
    resident = fixtures.create_resident(api)
    assert_versioned_resource(resident, expected_version=1)
    bumped = assert_ok(
        api.patch_marketing_preferences(
            resident["id"], factories.marketing_preferences_payload(True), admin_headers
        )
    )
    assert_versioned_resource(bumped, expected_version=2)

    response = api.create_consent_record(
        resident["id"],
        factories.utility_consent_payload(1),
        ops_headers,
    )

    assert_error(response, ApiErrorId.STALE_RESIDENT_VERSION, expected_status=412)
    assert_page(
        api.list_consent_records(admin_headers, resident_id=resident["id"]),
        total_count=0,
        has_more=False,
    )
    assert_unchanged(bumped, assert_ok(api.get_resident(resident["id"], admin_headers)))


def test_02_the_retry_quoting_the_fresh_resident_version_succeeds(api, ops_headers, admin_headers):
    """Re-reading the resident and quoting version 2 records the consent and advances to 3.

    PRD: "The record is created in `state` `GRANTED` with `granted_at` set to the
    current instant and with `revoked_at` and `revocation_reason` both null."
    PRD: "The resident's `version` is then incremented by one, and every
    non-terminal move of that resident has its `consent_gate` and
    `readiness_score` recomputed."

    Design: Corner/cross_cutting_complexity_layers/occ_consent_creation_rejects_a_stale_resident_version
    """
    resident = fixtures.create_resident(api)
    assert_ok(
        api.patch_marketing_preferences(
            resident["id"], factories.marketing_preferences_payload(True), admin_headers
        )
    )
    assert_error(
        api.create_consent_record(
            resident["id"], factories.utility_consent_payload(1), ops_headers
        ),
        ApiErrorId.STALE_RESIDENT_VERSION,
    )

    fresh = assert_ok(api.get_resident(resident["id"], admin_headers))
    consent = assert_created(
        api.create_consent_record(
            resident["id"], factories.utility_consent_payload(fresh["version"]), ops_headers
        )
    )

    assert consent["state"] == ConsentState.GRANTED.value, (
        f"expected GRANTED, got {consent['state']}"
    )
    assert consent["scope"] == ConsentScope.UTILITY_SETUP.value, (
        f"expected the UTILITY_SETUP scope, got {consent['scope']}"
    )
    after = assert_ok(api.get_resident(resident["id"], admin_headers))
    assert_version_bumped(fresh, after)


# ---------------------------------------------------------------------------
# Referral placement quotes the move version
# ---------------------------------------------------------------------------
def _move_ready_for_a_placement(api):
    """A SCHEDULING move holding marketing consent, with one capped internet partner."""
    network = fixtures.build_network(api)
    partner = fixtures.add_internet_partner(api, monthly_placement_cap=1)
    fixtures.grant_consents(
        api,
        network["resident"]["id"],
        [ConsentScope.PARTNER_MARKETING.value, ConsentScope.UTILITY_SETUP.value],
    )
    move = fixtures.ingest_move(api, network)
    fixtures.pass_identity_by_kba(api, move["id"])
    fixtures.run_mapping(api, move["id"], utility_types=[UtilityType.WATER.value])
    return {"network": network, "partner": partner, "move": fixtures.read_move(api, move["id"])}


def test_03_a_placement_quoting_the_previous_move_version_is_refused(api, ops_headers, admin_headers):
    """Quoting the version the move held one write ago consumes nothing.

    PRD: "Placing a partner referral against a move requires a non-optional
    `expected_move_version` field carrying the client's last observed `version`
    of that `MoveRecord`; a mismatch with the move's current `version` is
    rejected with `ERR_STALE_MOVE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_referral_placement_creation_rejects_a_stale_move_version
    """
    world = _move_ready_for_a_placement(api)
    stale_version = world["move"]["version"] - 1
    assert stale_version >= 1, (
        f"the setup must have advanced the move past version 1, got {world['move']['version']}"
    )

    response = api.create_placement(
        world["move"]["id"],
        factories.placement_payload(world["partner"]["id"], stale_version),
        ops_headers,
    )

    assert_error(response, ApiErrorId.STALE_MOVE_VERSION, expected_status=412)
    assert_page(
        api.list_placements(admin_headers, move_id=world["move"]["id"]),
        total_count=0,
        has_more=False,
    )


def test_04_the_retry_quoting_the_current_move_version_places_the_referral(api, ops_headers, admin_headers):
    """Re-reading the move and quoting its version creates the placement in PLACED.

    PRD: "The new row copies `vertical` from the partner, records `placed_at` as
    the current instant, opens in `placement_status` `PLACED` with `accepted_at`,
    `converted_at`, `decline_reason` and `reversal_reason` null"
    PRD: "adds one to the parent move's `version`"

    Design: Corner/cross_cutting_complexity_layers/occ_referral_placement_creation_rejects_a_stale_move_version
    """
    world = _move_ready_for_a_placement(api)
    assert_error(
        api.create_placement(
            world["move"]["id"],
            factories.placement_payload(world["partner"]["id"], world["move"]["version"] - 1),
            ops_headers,
        ),
        ApiErrorId.STALE_MOVE_VERSION,
    )

    fresh = fixtures.read_move(api, world["move"]["id"])
    placement = assert_created(
        api.create_placement(
            world["move"]["id"],
            factories.placement_payload(world["partner"]["id"], fresh["version"]),
            ops_headers,
        )
    )

    assert placement["placement_status"] == PlacementStatus.PLACED.value, (
        f"expected PLACED, got {placement['placement_status']}"
    )
    assert placement["vertical"] == PartnerVertical.INTERNET.value, (
        f"expected the partner's INTERNET vertical, got {placement['vertical']}"
    )
    assert_version_bumped(fresh, fixtures.read_move(api, world["move"]["id"]))
    assert_page(
        api.list_placements(admin_headers, move_id=world["move"]["id"]),
        total_count=1,
        has_more=False,
    )


# ---------------------------------------------------------------------------
# Duplicate resolution quotes the move version
# ---------------------------------------------------------------------------
def _suspected_duplicate_pair(api):
    """Two byte-identical ingestions, the second parked as a suspected duplicate."""
    network = fixtures.build_network(api)
    first = fixtures.ingest_move(api, network)
    second = fixtures.ingest_move(api, network)
    return {"network": network, "first": first, "second": fixtures.read_move(api, second["id"])}


def test_05_a_rescore_advances_the_move_and_strands_the_earlier_version(api, ops_headers):
    """After a RESCORE the pre-rescore version no longer authorises a dismissal.

    PRD: "Resolving a suspected duplicate likewise requires a non-optional
    `expected_move_version` matching the addressed move's current `version`, and
    a mismatch is rejected with `ERR_STALE_MOVE_VERSION` (HTTP 412)."
    PRD: "A `RESCORE` resolution re-runs the duplicate scoring from scratch
    against the current store and may either clear or preserve the `SUSPECTED`
    flag depending on the new score, likewise incrementing `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_duplicate_resolution_rejects_a_stale_move_version
    """
    world = _suspected_duplicate_pair(api)
    parked = world["second"]
    assert_move_state(
        parked,
        lifecycle_status=MoveLifecycleStatus.INTAKE.value,
        duplicate_flag=DuplicateFlag.SUSPECTED.value,
        blocked_reason=BlockedReason.DUPLICATE_SUSPECTED.value,
    )
    assert_duplicate_score(parked, 1.00)
    assert parked["duplicate_candidate_move_id"] == world["first"]["id"], (
        f"unexpected candidate {parked['duplicate_candidate_move_id']}"
    )
    stale_version = parked["version"]

    rescored = assert_ok(
        api.resolve_duplicate(
            parked["id"],
            factories.duplicate_resolution_payload(
                DuplicateResolution.RESCORE.value, stale_version
            ),
            ops_headers,
        )
    )
    assert_version_bumped(parked, rescored)
    assert_move_state(rescored, duplicate_flag=DuplicateFlag.SUSPECTED.value)

    refused = api.resolve_duplicate(
        parked["id"], factories.dismiss_payload(stale_version), ops_headers
    )
    assert_error(refused, ApiErrorId.STALE_MOVE_VERSION, expected_status=412)
    assert_unchanged(rescored, fixtures.read_move(api, parked["id"]))


def test_06_the_dismissal_quoting_the_rescored_version_clears_the_block(api, ops_headers):
    """DISMISS on the current version flags DISMISSED and leaves the lifecycle alone.

    PRD: "A `DISMISS` resolution leaves `lifecycle_status` entirely untouched,
    sets `duplicate_flag` to `DISMISSED`, clears `blocked_reason` back to `NONE`
    when it had been `DUPLICATE_SUSPECTED`, and increments the move's `version` by
    one."

    Design: Corner/cross_cutting_complexity_layers/occ_duplicate_resolution_rejects_a_stale_move_version
    """
    world = _suspected_duplicate_pair(api)
    parked = world["second"]
    rescored = assert_ok(
        api.resolve_duplicate(
            parked["id"],
            factories.duplicate_resolution_payload(
                DuplicateResolution.RESCORE.value, parked["version"]
            ),
            ops_headers,
        )
    )
    assert_error(
        api.resolve_duplicate(
            parked["id"], factories.dismiss_payload(parked["version"]), ops_headers
        ),
        ApiErrorId.STALE_MOVE_VERSION,
    )

    dismissed = assert_ok(
        api.resolve_duplicate(
            parked["id"], factories.dismiss_payload(rescored["version"]), ops_headers
        )
    )

    assert_move_state(
        dismissed,
        lifecycle_status=MoveLifecycleStatus.INTAKE.value,
        duplicate_flag=DuplicateFlag.DISMISSED.value,
        blocked_reason=BlockedReason.NONE.value,
    )
    assert_version_bumped(rescored, dismissed)


# ---------------------------------------------------------------------------
# A version advances once per write and never on a read
# ---------------------------------------------------------------------------
def test_07_repeated_reads_never_advance_a_resident_version(api, ops_headers, admin_headers):
    """The child consent write moves the resident from 1 to 2; three reads move nothing.

    PRD: "`version`, an integer that starts at 1 on creation and increments by
    one on every mutation of that row"
    PRD: "The resident's `version` is then incremented by one, and every
    non-terminal move of that resident has its `consent_gate` and
    `readiness_score` recomputed."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_once_per_write_and_never_on_a_read
    """
    resident = fixtures.create_resident(api)
    assert_versioned_resource(resident, expected_version=1)

    first_read = assert_ok(api.get_resident(resident["id"], admin_headers))
    second_read = assert_ok(api.get_resident(resident["id"], ops_headers))
    assert_unchanged(resident, first_read)
    assert_unchanged(resident, second_read)

    assert_created(
        api.create_consent_record(
            resident["id"], factories.utility_consent_payload(1), ops_headers
        )
    )

    after_write = assert_ok(api.get_resident(resident["id"], admin_headers))
    assert_versioned_resource(after_write, expected_version=2)
    assert_unchanged(after_write, assert_ok(api.get_resident(resident["id"], admin_headers)))


def test_08_the_move_version_walks_one_to_four_across_four_writes(api, ops_headers, gateway_headers):
    """Intake, opening the attempt, the vendor result and mapping each add exactly one.

    PRD: "`version`, an integer that starts at 1 on creation and increments by
    one on every mutation of that row"
    PRD: "every row a hop touches has its `updated_at` refreshed and its
    `version` incremented by one, exactly as any direct mutation would"

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_once_per_write_and_never_on_a_read
    """
    network = fixtures.build_network(api)
    fixtures.grant_consent(api, network["resident"]["id"], ConsentScope.UTILITY_SETUP.value, 1)

    ingested = fixtures.ingest_move(api, network)
    assert_versioned_resource(ingested, expected_version=1)

    verification = assert_created(
        api.create_identity_verification(
            ingested["id"], factories.kba_attempt_payload(), ops_headers
        )
    )
    after_open = fixtures.read_move(api, ingested["id"])
    assert_version_bumped(ingested, after_open)

    assert_ok(
        api.post_kba_result(
            verification["id"], factories.kba_result_payload(), gateway_headers
        )
    )
    after_result = fixtures.read_move(api, ingested["id"])
    assert_version_bumped(after_open, after_result)

    fixtures.run_mapping(api, ingested["id"], utility_types=[UtilityType.WATER.value])
    after_mapping = fixtures.read_move(api, ingested["id"])
    assert_version_bumped(after_result, after_mapping)

    assert after_mapping["version"] == 4, (
        f"four writes must leave the move at version 4, got {after_mapping['version']}"
    )
    assert_unchanged(after_mapping, fixtures.read_move(api, ingested["id"]))


# ---------------------------------------------------------------------------
# The feed source's accrued share reconciles to the ledger
# ---------------------------------------------------------------------------
def _two_converted_placements(api):
    """One rev-share and one flat-bounty placement, both CONVERTED on the same move."""
    network = fixtures.build_network(api)
    rev_share_partner = fixtures.add_internet_partner(api)
    bounty_partner = fixtures.add_insurance_partner(api)
    fixtures.grant_consents(
        api,
        network["resident"]["id"],
        [ConsentScope.PARTNER_MARKETING.value, ConsentScope.UTILITY_SETUP.value],
    )
    move = fixtures.ingest_move(api, network)
    fixtures.pass_identity_by_kba(api, move["id"])

    placements = {}
    for partner in (rev_share_partner, bounty_partner):
        current = fixtures.read_move(api, move["id"])
        placement = fixtures.place_referral(
            api, move["id"], partner["id"], current["version"]
        )
        headers = make_partner_agent_headers(partner["id"])
        assert_ok(api.accept_placement(placement["id"], {}, headers))
        placements[partner["id"]] = assert_ok(
            api.convert_placement(placement["id"], factories.conversion_payload(100000), headers)
        )
    return {
        "network": network,
        "rev_share_partner": rev_share_partner,
        "bounty_partner": bounty_partner,
        "rev_share_placement": placements[rev_share_partner["id"]],
        "bounty_placement": placements[bounty_partner["id"]],
    }


def test_09_the_accrued_share_is_the_sum_of_the_two_converted_placements(api):
    """Two conversions on two payout models add up to the feed source's balance.

    PRD: "a gross of 100000 cents against a 0.3000 revenue share yields a
    provisional commission of 27000 cents; a feed source on a 0.1750 share takes
    4725 cents of it; the platform keeps 22275 cents"
    PRD: "`accrued_share_cents` on a `FeedSource` is the sum of the
    already-rounded per-placement `feed_source_share_cents` over that source's
    placements in `CONVERTED` or `SETTLED`"

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_feed_accrual_equals_the_ledger_share_sum
    """
    world = _two_converted_placements(api)

    assert_cents(world["rev_share_placement"], "attributed_share_cents", 27000)
    assert_cents(world["rev_share_placement"], "feed_source_share_cents", 4725)
    assert_cents(world["bounty_placement"], "attributed_share_cents", 5000)
    assert_cents(world["bounty_placement"], "feed_source_share_cents", 875)

    feed = fixtures.read_feed_source(api, world["network"]["feed_source"]["id"])
    expected = (
        world["rev_share_placement"]["feed_source_share_cents"]
        + world["bounty_placement"]["feed_source_share_cents"]
    )
    assert_cents(feed, "accrued_share_cents", expected)
    assert_cents(feed, "accrued_share_cents", 5600)


def test_10_a_reversal_returns_the_accrual_to_the_signed_ledger_sum(api, admin_headers):
    """Reversing the bounty placement drops it out of the balance the ledger still records.

    PRD: "Reversal posts a `REVERSAL` entry for the negative of the current
    `attributed_share_cents` and a `FEED_SOURCE_SHARE_REVERSAL` entry for the
    positive of the current `feed_source_share_cents`, then resets both share
    fields to 0 and moves `placement_status` to `REVERSED`."
    PRD: "`accrued_share_cents` on a `FeedSource` is the sum of the
    already-rounded per-placement `feed_source_share_cents` over that source's
    placements in `CONVERTED` or `SETTLED`"

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_feed_accrual_equals_the_ledger_share_sum
    """
    world = _two_converted_placements(api)

    reversed_placement = assert_ok(
        api.reverse_placement(
            world["bounty_placement"]["id"], factories.reversal_payload(), admin_headers
        )
    )
    assert reversed_placement["placement_status"] == PlacementStatus.REVERSED.value, (
        f"expected REVERSED, got {reversed_placement['placement_status']}"
    )
    assert_cents(reversed_placement, "attributed_share_cents", 0)
    assert_cents(reversed_placement, "feed_source_share_cents", 0)

    feed = fixtures.read_feed_source(api, world["network"]["feed_source"]["id"])
    assert_cents(feed, "accrued_share_cents", 4725)

    entries = assert_page(api.list_ledger_entries(admin_headers), total_count=6, has_more=False)
    share_entries = [
        entry
        for entry in entries
        if entry["entry_type"]
        in (
            LedgerEntryType.FEED_SOURCE_SHARE.value,
            LedgerEntryType.FEED_SOURCE_SHARE_REVERSAL.value,
        )
    ]
    signed_sum = sum(entry["amount_cents"] for entry in share_entries)
    assert -signed_sum == feed["accrued_share_cents"], (
        f"the feed share entries sum to {signed_sum}, which does not reconcile with "
        f"accrued_share_cents {feed['accrued_share_cents']}"
    )
