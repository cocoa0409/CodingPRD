"""Resource shapes, declared defaults, computed fields and list bookkeeping.

Every test in this file builds its own world through declared endpoints and
asserts the shape the PRD promises for one resource family: the fields a
creation echoes back, the values an omitted optional input falls back to, the
digest the server derives, the 404 an unresolvable identifier produces, and
the window bookkeeping a collection endpoint reports.  The logical clock is
pinned at its mandatory startup default wherever a written timestamp or a
date comparison matters.
"""

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_all_distinct,
    assert_cents,
    assert_created,
    assert_duplicate_score,
    assert_entry_types,
    assert_error,
    assert_immutable_resource,
    assert_ledger_net,
    assert_list,
    assert_move_state,
    assert_ok,
    assert_page,
    assert_pct_field,
    assert_versioned_resource,
)
from test_helpers.constants import CLOCK_STARTUP_DEFAULT, NON_EXISTENT_UUID
from test_helpers.types import (
    BlockedReason,
    ConsentGate,
    DuplicateFlag,
    FeedStatus,
    LedgerEntryType,
    MoveLifecycleStatus,
    TrustTier,
)


def test_01_resident_creation_returns_every_declared_field_and_default(api, admin_headers):
    """A created resident echoes its five identity inputs and takes both declared defaults.

    PRD: "An optional `marketing_opt_out` boolean defaults to false. A fresh
    resident starts at `version` 1 with `opted_out_at` null."

    Design: Corner/entities/creation_resident_returns_201_with_every_declared_field
    """
    fixtures.set_clock(api, CLOCK_STARTUP_DEFAULT)

    response = api.create_resident(factories.resident_payload(), admin_headers)
    resident = assert_created(response)

    assert resident["full_name"] == "Dana Ruiz", f"expected full_name Dana Ruiz, got {resident['full_name']}"
    assert resident["email"] == "dana.ruiz@example.com", f"unexpected email {resident['email']}"
    assert resident["phone_last4"] == "4417", f"unexpected phone_last4 {resident['phone_last4']}"
    assert resident["date_of_birth"] == "1988-04-12", f"unexpected date_of_birth {resident['date_of_birth']}"
    assert resident["ssn_last4"] == "6621", f"unexpected ssn_last4 {resident['ssn_last4']}"

    assert resident["marketing_opt_out"] is False, "marketing_opt_out must default to false"
    assert resident["opted_out_at"] is None, "a fresh resident must carry opted_out_at null"
    assert_versioned_resource(resident, expected_version=1)


def test_02_feed_source_omitted_options_take_declared_defaults(api, admin_headers):
    """A feed registered without the two optional inputs falls back to 30 days and TIER_B.

    PRD: "it accepts 1 through 120 and defaults to 30 when omitted"
    PRD: "A newly registered feed starts with `accrued_share_cents` at 0 and
    `feed_status` at `ACTIVE`."

    Design: Corner/entities/defaults_feed_source_dedupe_window_and_trust_tier_applied
    """
    fixtures.set_clock(api, CLOCK_STARTUP_DEFAULT)

    payload = factories.feed_source_payload(name="Coastal Mover Feed", source_type="MOVER")
    payload.pop("dedupe_window_days")
    payload.pop("trust_tier")

    created = assert_created(api.create_feed_source(payload, admin_headers))
    assert created["dedupe_window_days"] == 30, (
        f"expected dedupe_window_days 30, got {created['dedupe_window_days']}"
    )
    assert created["trust_tier"] == TrustTier.TIER_B.value, (
        f"expected trust_tier TIER_B, got {created['trust_tier']}"
    )
    assert_cents(created, "accrued_share_cents", 0)
    assert created["feed_status"] == FeedStatus.ACTIVE.value, (
        f"expected feed_status ACTIVE, got {created['feed_status']}"
    )

    reread = assert_ok(api.get_feed_source(created["id"], admin_headers))
    assert reread["dedupe_window_days"] == 30, "the dedupe window default was not persisted"
    assert reread["trust_tier"] == TrustTier.TIER_B.value, "the trust tier default was not persisted"
    assert_cents(reread, "accrued_share_cents", 0)
    assert reread["feed_status"] == FeedStatus.ACTIVE.value, "the feed status default was not persisted"


def test_03_service_address_hash_normalizes_case_and_unit(api, admin_headers):
    """The derived digest folds case, treats a null unit as the empty string and reads postal code.

    PRD: "`address_hash` is a deterministic digest formed by concatenating the
    lower-cased `line1`, a vertical-bar separator, the lower-cased `unit` (an
    empty string when `unit` is null), another vertical bar, and the
    `postal_code`"

    Design: Corner/entities/computed_fields_service_address_hash_normalizes_case_and_unit
    """
    fixtures.set_clock(api, CLOCK_STARTUP_DEFAULT)

    mixed_case = assert_created(
        api.create_service_address(factories.destination_address_payload(), admin_headers)
    )
    folded = assert_created(
        api.create_service_address(
            factories.destination_address_payload(
                line1="402 peachtree way", unit="7b", city="ATLANTA"
            ),
            admin_headers,
        )
    )
    no_unit_payload = factories.destination_address_payload()
    no_unit_payload.pop("unit")
    no_unit = assert_created(api.create_service_address(no_unit_payload, admin_headers))
    other_postal = assert_created(
        api.create_service_address(
            factories.destination_address_payload(postal_code="30303"), admin_headers
        )
    )

    assert folded["address_hash"] == mixed_case["address_hash"], (
        "line1 and unit must be lower-cased before the digest is formed"
    )
    assert no_unit["address_hash"] != mixed_case["address_hash"], (
        "a null unit hashes as the empty string, not as the unit designator 7B"
    )
    assert other_postal["address_hash"] != mixed_case["address_hash"], (
        "postal_code participates in the digest"
    )

    for address in (mixed_case, folded, no_unit, other_postal):
        assert address["usps_deliverable"] is True, (
            f"postal_code {address['postal_code']} does not begin with 000 and is deliverable"
        )
    assert_all_distinct(
        [mixed_case["id"], folded["id"], no_unit["id"], other_postal["id"]]
    )


def test_04_unknown_utility_order_id_returns_order_not_found(api, ops_headers):
    """Reading a service order that was never mapped answers the order-specific 404.

    PRD: "a missing service order `ERR_UTILITY_ORDER_NOT_FOUND`, a missing
    credit-check handoff `ERR_HANDOFF_NOT_FOUND`"

    Design: Corner/entities/not_found_unknown_utility_order_path_id_returns_404
    """
    fixtures.set_clock(api, CLOCK_STARTUP_DEFAULT)

    response = api.get_utility_order(NON_EXISTENT_UUID, ops_headers)
    assert_error(response, ApiErrorId.UTILITY_ORDER_NOT_FOUND)


def test_05_filing_under_unknown_move_returns_move_not_found(api, ops_headers):
    """Drafting a postal filing under an unresolvable move answers the move 404, not a business error.

    PRD: "Path identifiers are resolved strictly left to right, and the first
    identifier that fails to resolve decides the error"

    Design: Corner/entities/parent_relationships_filing_under_unknown_move_returns_move_not_found
    """
    fixtures.set_clock(api, CLOCK_STARTUP_DEFAULT)

    response = api.create_filing(
        NON_EXISTENT_UUID, factories.filing_payload(forward_start_date="2026-08-20"), ops_headers
    )
    assert_error(response, ApiErrorId.MOVE_NOT_FOUND)


def test_06_move_ingestion_without_move_date_is_rejected(api, ops_headers):
    """A body missing the required physical move date is refused and nothing is stored.

    PRD: "every required field present and non-null, no unknown enum member,
    integers inside their declared ranges"

    Design: Corner/entities/required_fields_move_creation_missing_required_move_date_rejected
    """
    network = fixtures.build_network(api, clock=CLOCK_STARTUP_DEFAULT)

    payload = factories.move_payload(
        network["resident"]["id"],
        network["feed_source"]["id"],
        network["origin_address"]["id"],
        network["destination_address"]["id"],
    )
    payload.pop("move_date")

    assert_error(api.create_move(payload, ops_headers), ApiErrorId.INVALID_REQUEST)

    assert_page(
        api.list_moves(ops_headers, resident_id=network["resident"]["id"]),
        total_count=0,
        has_more=False,
    )


def test_07_address_and_partner_field_constraints_are_rejected(api, admin_headers):
    """A four-digit postal code, a lower-case state code and an unknown vertical are all refused.

    PRD: "`state_code` (exactly two upper-case letters), `postal_code` (exactly
    five digits), and an optional `unit` designator that defaults to null"

    Design: Corner/entities/type_constraints_address_and_partner_ranges_rejected
    """
    fixtures.set_clock(api, CLOCK_STARTUP_DEFAULT)

    assert_error(
        api.create_service_address(
            factories.destination_address_payload(postal_code="3030"), admin_headers
        ),
        ApiErrorId.INVALID_REQUEST,
    )
    assert_error(
        api.create_service_address(
            factories.destination_address_payload(state_code="ga"), admin_headers
        ),
        ApiErrorId.INVALID_REQUEST,
    )
    assert_error(
        api.create_referral_partner(
            factories.internet_partner_payload(vertical="SOLAR"), admin_headers
        ),
        ApiErrorId.INVALID_REQUEST,
    )


def test_08_partner_revenue_share_ceiling_is_inclusive(api, admin_headers):
    """A partner registered at exactly the top of the declared band is accepted.

    PRD: "`referral_revenue_share_pct` runs from 0.0000 through 0.5000 inclusive,
    `rev_share_pct` from 0.0000 through 0.9000 inclusive."

    Design: Corner/entities/type_constraints_address_and_partner_ranges_rejected
    """
    fixtures.set_clock(api, CLOCK_STARTUP_DEFAULT)

    partner = assert_created(
        api.create_referral_partner(
            factories.internet_partner_payload(rev_share_pct=0.9), admin_headers
        )
    )
    assert_pct_field(partner, "rev_share_pct", 0.9000)


def test_09_move_read_back_exposes_stored_intake_fields(api, ops_headers):
    """Re-reading an ingested move returns its four foreign keys and every intake default.

    PRD: "A newly ingested move lands in `lifecycle_status` `INTAKE` with
    `verified_at` null, `identity_attempt_count` at 0, `mapped_order_count` at 0"

    Design: Corner/entities/retrieval_move_returns_stored_intake_fields
    """
    network = fixtures.build_network(api, clock=CLOCK_STARTUP_DEFAULT)
    created = fixtures.ingest_move(
        api, network, move_date="2026-08-20", external_reference="PM-77"
    )

    move = assert_ok(api.get_move(created["id"], ops_headers))

    assert move["id"] == created["id"], "the read must address the same move"
    assert move["resident_id"] == network["resident"]["id"], "resident_id was not stored"
    assert move["feed_source_id"] == network["feed_source"]["id"], "feed_source_id was not stored"
    assert move["origin_address_id"] == network["origin_address"]["id"], "origin_address_id was not stored"
    assert move["destination_address_id"] == network["destination_address"]["id"], (
        "destination_address_id was not stored"
    )
    assert move["move_date"] == "2026-08-20", f"unexpected move_date {move['move_date']}"
    assert move["external_reference"] == "PM-77", "the feed's own identifier must be echoed back"

    assert_move_state(
        move,
        lifecycle_status=MoveLifecycleStatus.INTAKE.value,
        duplicate_flag=DuplicateFlag.NONE.value,
        consent_gate=ConsentGate.OPEN.value,
        blocked_reason=BlockedReason.NONE.value,
        readiness_score=0,
    )
    assert_duplicate_score(move, 0.00)
    assert move["duplicate_candidate_move_id"] is None, "no candidate was found, so the key stays null"
    assert move["reactivation_candidate_move_id"] is None, "no cancelled predecessor exists"
    assert move["duplicate_of_move_id"] is None, "an unresolved move carries duplicate_of_move_id null"
    assert move["verified_at"] is None, "an unverified move carries verified_at null"
    assert move["identity_attempt_count"] == 0, "no identity attempt has been opened"
    assert move["mapped_order_count"] == 0, "no provider mapping has run"
    assert move["unmapped_utility_types"] == [], "unmapped_utility_types starts empty"
    assert_versioned_resource(move, expected_version=1)


def test_10_move_system_fields_are_server_generated(api, ops_headers):
    """The identifier, timestamps, lifecycle state and readiness score are the server's to set.

    PRD: "Every persisted resource carries a server-minted `id` in UUID form,
    with no type prefix and no client control over its value"

    Design: Corner/entities/system_fields_move_timestamps_generated_and_lifecycle_input_ignored
    """
    network = fixtures.build_network(api, clock=CLOCK_STARTUP_DEFAULT)

    honest = assert_created(
        api.create_move(
            factories.move_payload(
                network["resident"]["id"],
                network["feed_source"]["id"],
                network["origin_address"]["id"],
                network["destination_address"]["id"],
                move_date="2026-08-20",
            ),
            ops_headers,
        )
    )
    assert honest["lifecycle_status"] == MoveLifecycleStatus.INTAKE.value, (
        "ingestion always lands in INTAKE"
    )
    assert honest["readiness_score"] == 0, "readiness is derived, and starts at 0"
    assert_versioned_resource(honest, expected_version=1)

    api.create_move(
        factories.move_payload(
            network["resident"]["id"],
            network["feed_source"]["id"],
            network["origin_address"]["id"],
            network["destination_address"]["id"],
            move_date="2026-08-21",
            lifecycle_status=MoveLifecycleStatus.VERIFIED.value,
            readiness_score=99,
        ),
        ops_headers,
    )

    rows, _meta = assert_list(
        api.list_moves(ops_headers, resident_id=network["resident"]["id"])
    )
    assert rows, "the honest ingestion must still be listed"
    for row in rows:
        assert row["lifecycle_status"] == MoveLifecycleStatus.INTAKE.value, (
            "a client-supplied lifecycle_status must never be honoured"
        )
        assert row["readiness_score"] == 0, "a client-supplied readiness_score must never be honoured"
        assert row["verified_at"] is None, "no move here has cleared identity"


def test_11_move_listing_reports_window_bookkeeping(api, ops_headers):
    """Two windows over three unrelated moves report the pre-window count and the remainder flag.

    PRD: "the `meta` object carries `limit`, `offset`, `total_count` (the number
    of rows matching the filters before the page window is applied) and
    `has_more` (true when rows remain after the current window)"

    Design: Corner/entities/listing_moves_pagination_reports_total_count_and_has_more
    """
    network = fixtures.build_network(api, clock=CLOCK_STARTUP_DEFAULT)
    second = fixtures.create_resident(
        api,
        full_name="Ivan Cole",
        email="ivan.cole@example.com",
        phone_last4="9052",
        date_of_birth="1979-11-02",
        ssn_last4="3318",
    )
    third = fixtures.create_second_resident(api)
    second_destination = fixtures.create_destination_address(api, line1="915 Juniper St", unit="2A")
    third_destination = fixtures.create_address(api, factories.third_address_payload())

    fixtures.ingest_move(api, network, move_date="2026-08-10", external_reference="PM-P1")
    assert_created(
        api.create_move(
            factories.move_payload(
                second["id"],
                network["feed_source"]["id"],
                network["origin_address"]["id"],
                second_destination["id"],
                move_date="2026-08-20",
                external_reference="PM-P2",
            ),
            ops_headers,
        )
    )
    assert_created(
        api.create_move(
            factories.move_payload(
                third["id"],
                network["feed_source"]["id"],
                network["origin_address"]["id"],
                third_destination["id"],
                move_date="2026-08-30",
                external_reference="PM-P3",
            ),
            ops_headers,
        )
    )

    first_page = assert_page(
        api.list_moves(ops_headers, limit=2, offset=0),
        total_count=3,
        has_more=True,
        limit=2,
        offset=0,
    )
    assert len(first_page) == 2, f"a limit of 2 must return 2 rows, got {len(first_page)}"

    second_page = assert_page(
        api.list_moves(ops_headers, limit=2, offset=2),
        total_count=3,
        has_more=False,
        limit=2,
        offset=2,
    )
    assert len(second_page) == 1, f"the tail window must return 1 row, got {len(second_page)}"

    for row in first_page + second_page:
        assert row["duplicate_flag"] == DuplicateFlag.NONE.value, (
            "these three households share no identity signal, so none is a duplicate"
        )
    assert_all_distinct([row["id"] for row in first_page + second_page])


def test_12_move_listing_combines_filters_conjunctively(api, ops_headers):
    """A lifecycle filter and a resident filter together narrow to the single matching move.

    PRD: "Filter parameters on list endpoints are combined conjunctively: a
    listing that supplies both a status filter and a foreign-key filter returns
    only rows satisfying both."

    Design: Corner/entities/listing_moves_pagination_reports_total_count_and_has_more
    """
    network = fixtures.build_network(api, clock=CLOCK_STARTUP_DEFAULT)
    second = fixtures.create_resident(
        api,
        full_name="Ivan Cole",
        email="ivan.cole@example.com",
        phone_last4="9052",
        date_of_birth="1979-11-02",
        ssn_last4="3318",
    )
    second_destination = fixtures.create_destination_address(api, line1="915 Juniper St", unit="2A")

    fixtures.ingest_move(api, network, move_date="2026-08-10", external_reference="PM-P1")
    target = assert_created(
        api.create_move(
            factories.move_payload(
                second["id"],
                network["feed_source"]["id"],
                network["origin_address"]["id"],
                second_destination["id"],
                move_date="2026-08-20",
                external_reference="PM-P2",
            ),
            ops_headers,
        )
    )

    rows = assert_page(
        api.list_moves(
            ops_headers,
            lifecycle_status=MoveLifecycleStatus.INTAKE.value,
            resident_id=second["id"],
            limit=2,
        ),
        total_count=1,
        has_more=False,
        limit=2,
    )
    assert len(rows) == 1, f"only Ivan Cole's move satisfies both filters, got {len(rows)}"
    assert rows[0]["id"] == target["id"], "the conjunctive filter returned the wrong move"
    assert rows[0]["external_reference"] == "PM-P2", "the wrong feed reference came back"


def test_13_territory_junction_links_provider_and_is_discoverable(api, admin_headers):
    """A coverage row links a provider to a postal code open-endedly and lists under both filters.

    PRD: "an optional `effective_to` date that is the last date inclusive and
    means open-ended when null"

    Design: Corner/entities/graph_topology_territory_junction_links_provider_and_rejects_unknown_reference_not_found
    """
    fixtures.set_clock(api, CLOCK_STARTUP_DEFAULT)
    provider = fixtures.create_provider(api, factories.electric_provider_payload())

    territory = assert_created(
        api.create_territory(factories.territory_payload(provider["id"]), admin_headers)
    )
    assert territory["provider_id"] == provider["id"], "the junction row must name its provider"
    assert territory["postal_code"] == "30302", f"unexpected postal_code {territory['postal_code']}"
    assert territory["state_code"] == "GA", f"unexpected state_code {territory['state_code']}"
    assert territory["effective_from"] == "2026-01-01", "effective_from was not stored"
    assert territory["effective_to"] is None, "an omitted effective_to means open-ended"
    assert territory["priority_rank"] == 1, f"unexpected priority_rank {territory['priority_rank']}"
    assert territory["is_default_carrier"] is True, "the default-carrier flag was not stored"

    rows = assert_page(
        api.list_territories(admin_headers, provider_id=provider["id"], postal_code="30302"),
        total_count=1,
        has_more=False,
    )
    assert rows[0]["id"] == territory["id"], "the coverage row is not discoverable under both filters"


def test_14_territory_with_unknown_provider_reference_is_rejected(api, admin_headers):
    """A coverage row naming a provider that does not exist is refused and nothing is stored.

    PRD: "any of them fails to resolve to an existing row, the request is
    rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 404). This applies to move
    ingestion, territory declaration"

    Design: Corner/entities/graph_topology_territory_junction_links_provider_and_rejects_unknown_reference_not_found
    """
    fixtures.set_clock(api, CLOCK_STARTUP_DEFAULT)
    provider = fixtures.create_provider(api, factories.electric_provider_payload())
    fixtures.create_territory(api, provider["id"])

    response = api.create_territory(
        factories.territory_payload(
            NON_EXISTENT_UUID, postal_code="30305", priority_rank=2, is_default_carrier=False
        ),
        admin_headers,
    )
    assert_error(response, ApiErrorId.REFERENCE_NOT_FOUND)

    rows = assert_page(
        api.list_territories(admin_headers, postal_code="30305"), total_count=0, has_more=False
    )
    assert rows == [], "the rejected declaration must not have created a coverage row"
    assert_page(
        api.list_territories(admin_headers, provider_id=provider["id"]),
        total_count=1,
        has_more=False,
    )


def test_15_ledger_entries_carry_no_update_or_version_fields(api, admin_headers):
    """The two entries a conversion journals expose their denormalised keys and nothing mutable.

    PRD: "A ledger entry has **no** `updated_at` field and **no** `version`
    field, and neither key appears in its response body."

    Design: Corner/entities/immutability_revenue_share_ledger_entry_has_no_update_path_or_version
    """
    bundle = fixtures.converted_referral(api, gross_revenue_cents=100000)
    placement = bundle["placement"]

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

    for entry in entries:
        assert_immutable_resource(entry)
        assert entry["placement_id"] == placement["id"], "placement_id is denormalised onto the entry"
        assert entry["move_id"] == bundle["move"]["id"], "move_id is denormalised onto the entry"
        assert entry["feed_source_id"] == bundle["feed_source"]["id"], (
            "feed_source_id is denormalised onto the entry"
        )
        assert entry["posted_at"], "every entry carries a posted_at instant"

    reread = assert_ok(api.get_ledger_entry(entries[0]["id"], admin_headers))
    assert_immutable_resource(reread)
    assert reread["id"] == entries[0]["id"], "the read must address the same entry"


def test_16_settlement_appends_adjustment_entries_without_restating(api, admin_headers):
    """Settling on the final gross posts only the two deltas and leaves the accrual rows alone.

    PRD: "the ledger receives an `ADJUSTMENT` of positive 3000 and a
    `FEED_SOURCE_SHARE_ADJUSTMENT` of negative 525 — never a restatement of the
    original figures"

    Design: Corner/entities/immutability_revenue_share_ledger_entry_has_no_update_path_or_version
    """
    bundle = fixtures.converted_referral(api, gross_revenue_cents=100000)
    placement_id = bundle["placement"]["id"]

    before = assert_page(
        api.list_ledger_entries(admin_headers, placement_id=placement_id), total_count=2
    )

    settled = assert_ok(
        api.settle_placement(
            placement_id, factories.settlement_payload(settled_gross_revenue_cents=100000), admin_headers
        )
    )

    after = assert_page(
        api.list_ledger_entries(admin_headers, placement_id=placement_id),
        total_count=4,
        has_more=False,
    )
    assert_entry_types(
        after,
        [
            LedgerEntryType.ACCRUAL.value,
            LedgerEntryType.FEED_SOURCE_SHARE.value,
            LedgerEntryType.ADJUSTMENT.value,
            LedgerEntryType.FEED_SOURCE_SHARE_ADJUSTMENT.value,
        ],
    )
    assert after[0] == before[0], "the original accrual must not be restated"
    assert after[1] == before[1], "the original feed-source share must not be restated"
    assert_cents(after[2], "amount_cents", 3000)
    assert_cents(after[3], "amount_cents", -525)
    for entry in after:
        assert_immutable_resource(entry)
    assert_ledger_net(after, settled)
