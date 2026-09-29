"""Resource shape, declared defaults and input handling.

Every test in this file builds its own world through the declared endpoints:
the service is restarted against an empty database before each one, so nothing
is inherited from a neighbouring test.
"""

import pytest

from test_helpers import (
    api_errors as E,
    assert_common_fields,
    assert_created_at_ascending,
    assert_millisecond_precision,
    assert_no_pagination_meta,
    assert_tier_inventory_conserved,
    assert_timestamp_equals,
    factories as f,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import DEFAULT_CLOCK

# A syntactically valid UUID that is never allocated by any create call below.
UNALLOCATED_UUID = "00000000-0000-4000-8000-000000000001"
SECOND_UNALLOCATED_UUID = "00000000-0000-4000-8000-0000000000bb"
FORGED_UUID = "00000000-0000-4000-8000-0000000000ff"


# ---------------------------------------------------------------------------
# Shared worlds
# ---------------------------------------------------------------------------


def _stored_show_world(build):
    """One market, one act, one building and one CO_PROMOTE date at it."""
    market = build.market(
        name="Southeast", region_code="SEA", guarantee_exposure_limit_cents=9_000_000
    )
    artist = build.artist(
        name="Pinewood Static",
        agency="Magnolia Talent",
        tier="CLUB",
        historical_sellthrough_pct=47.50,
        withholding_pct=0,
    )
    venue = build.venue(
        market["id"],
        name="Magnolia Room",
        gross_capacity=800,
        facility_fee_cents_per_ticket=200,
        ticket_tax_pct=5.00,
    )
    show = build.show(
        artist["id"],
        venue["id"],
        event_at="2026-10-03T02:00:00.000Z",
        load_in_at="2026-10-02T14:00:00.000Z",
        load_out_at="2026-10-03T08:00:00.000Z",
        announce_at="2026-08-12T15:00:00.000Z",
        venue_arrangement="CO_PROMOTE",
        rental_fee_cents=0,
        copromote_venue_share_pct=12.50,
        venue_expense_pct_production=40.00,
        venue_expense_pct_marketing=0,
        venue_expense_pct_staffing=0,
        venue_expense_pct_hospitality=0,
    )
    return {"market": market, "artist": artist, "venue": venue, "show": show}


def _show_index_world(build):
    """Five dates at one building, three of them confirmed by an accepted offer."""
    market = build.market(
        name="Listing Market",
        region_code="LST",
        guarantee_exposure_limit_cents=20_000_000,
    )
    venue = build.venue(
        market["id"],
        name="Index Hall",
        gross_capacity=1_000,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
    )
    names = ["Act One", "Act Two", "Act Three", "Act Four", "Act Five"]
    artists = [
        build.artist(
            name=name,
            agency="Index Talent",
            tier="CLUB",
            historical_sellthrough_pct=40.00 + index,
            withholding_pct=0,
        )
        for index, name in enumerate(names)
    ]
    shows = []
    for index, artist in enumerate(artists):
        day = 2 + 2 * index
        shows.append(
            build.show(
                artist["id"],
                venue["id"],
                event_at=f"2026-10-{day:02d}T02:00:00.000Z",
                load_in_at=f"2026-10-{day - 1:02d}T14:00:00.000Z",
                load_out_at=f"2026-10-{day:02d}T08:00:00.000Z",
                announce_at="2026-08-20T15:00:00.000Z",
                venue_arrangement="RENTAL",
                rental_fee_cents=50_000,
            )
        )
    for artist, show in zip(artists[:3], shows[:3]):
        build.accepted_offer(
            show["id"],
            artist["id"],
            deal_structure="FLAT_GUARANTEE",
            guarantee_cents=1_000_000,
            deposit_cents=0,
            expense_cap_cents=1_000_000,
        )
    return {"market": market, "venue": venue, "artists": artists, "shows": shows}


def _required_fields_world(build):
    """A PLANNED date whose version is the one an offer body must quote."""
    market = build.market(
        name="Required Market", region_code="REQ", guarantee_exposure_limit_cents=9_000_000
    )
    artist = build.artist(
        name="Required Act",
        agency="Req Talent",
        tier="THEATER",
        historical_sellthrough_pct=60.00,
    )
    venue = build.venue(
        market["id"],
        name="Required Hall",
        gross_capacity=1_200,
        facility_fee_cents_per_ticket=150,
        ticket_tax_pct=4.00,
    )
    show = build.show(
        artist["id"],
        venue["id"],
        event_at="2026-11-05T02:00:00.000Z",
        load_in_at="2026-11-04T14:00:00.000Z",
        load_out_at="2026-11-05T08:00:00.000Z",
        announce_at="2026-08-15T15:00:00.000Z",
        venue_arrangement="RENTAL",
        rental_fee_cents=120_000,
    )
    return {"market": market, "artist": artist, "venue": venue, "show": show}


def _full_offer_payload(show):
    return {
        "show_id": show["id"],
        "expected_show_version": show["version"],
        "deal_structure": "FLAT_GUARANTEE",
        "guarantee_cents": 2_000_000,
        "deposit_cents": 0,
        "expense_cap_cents": 1_000_000,
    }


def _defaults_world(build):
    """A market and a building; every row under test is created by the test."""
    market = build.market(
        name="Default Market", region_code="DEF", guarantee_exposure_limit_cents=9_000_000
    )
    venue = build.venue(
        market["id"],
        name="Default Hall",
        gross_capacity=900,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
    )
    return {"market": market, "venue": venue}


def _defaults_show(build, world):
    artist = build.artist(
        name="Default Act",
        agency="Def Talent",
        tier="CLUB",
        historical_sellthrough_pct=55.00,
    )
    show = build.show(
        artist["id"],
        world["venue"]["id"],
        event_at="2026-11-12T02:00:00.000Z",
        load_in_at="2026-11-11T14:00:00.000Z",
        load_out_at="2026-11-12T08:00:00.000Z",
        announce_at="2026-08-18T15:00:00.000Z",
        venue_arrangement="RENTAL",
        rental_fee_cents=90_000,
    )
    return artist, show


def _system_fields_world(build):
    """Two markets, so a supplied market_id can name a real-but-wrong market."""
    true_market = build.market(
        name="True Market", region_code="TRU", guarantee_exposure_limit_cents=5_000_000
    )
    decoy_market = build.market(
        name="Decoy Market", region_code="DCY", guarantee_exposure_limit_cents=5_000_000
    )
    artist = build.artist(
        name="System Act",
        agency="Sys Talent",
        tier="THEATER",
        historical_sellthrough_pct=65.00,
    )
    venue = build.venue(
        true_market["id"],
        name="System Hall",
        gross_capacity=1_000,
        facility_fee_cents_per_ticket=100,
        ticket_tax_pct=3.00,
    )
    return {
        "true_market": true_market,
        "decoy_market": decoy_market,
        "artist": artist,
        "venue": venue,
    }


def _forged_show_payload(world):
    return {
        "artist_id": world["artist"]["id"],
        "venue_id": world["venue"]["id"],
        "event_at": "2026-11-26T02:00:00.000Z",
        "load_in_at": "2026-11-25T14:00:00.000Z",
        "load_out_at": "2026-11-26T08:00:00.000Z",
        "announce_at": "2026-08-22T15:00:00.000Z",
        "venue_arrangement": "RENTAL",
        "rental_fee_cents": 110_000,
        "id": FORGED_UUID,
        "market_id": world["decoy_market"]["id"],
        "show_status": "PERFORMED",
        "sales_status": "CLOSED",
        "version": 99,
        "created_at": "2020-01-01T00:00:00.000Z",
        "updated_at": "2020-01-01T00:00:00.000Z",
        "exposure_override_limit_cents": 999_999_999,
        "exposure_override_by_user_id": "u_forged",
    }


def _type_constraint_world(build):
    """A PLANNED date, so every probe below fails only on the field under test."""
    market = build.market(
        name="Type Market", region_code="TYP", guarantee_exposure_limit_cents=6_000_000
    )
    artist = build.artist(
        name="Type Act",
        agency="Typ Talent",
        tier="CLUB",
        historical_sellthrough_pct=50.00,
    )
    venue = build.venue(
        market["id"],
        name="Type Hall",
        gross_capacity=700,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
    )
    show = build.show(
        artist["id"],
        venue["id"],
        event_at="2026-12-03T02:00:00.000Z",
        load_in_at="2026-12-02T14:00:00.000Z",
        load_out_at="2026-12-03T08:00:00.000Z",
        announce_at="2026-08-25T15:00:00.000Z",
        venue_arrangement="RENTAL",
        rental_fee_cents=80_000,
    )
    return {"market": market, "artist": artist, "venue": venue, "show": show}


def _parent_fk_world(build):
    """A market, an act, a building, a PLANNED date and one tier on it."""
    market = build.market(
        name="Parent Market", region_code="PAR", guarantee_exposure_limit_cents=6_000_000
    )
    artist = build.artist(
        name="Parent Act",
        agency="Par Talent",
        tier="CLUB",
        historical_sellthrough_pct=50.00,
    )
    venue = build.venue(
        market["id"],
        name="Parent Hall",
        gross_capacity=700,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
    )
    show = build.show(
        artist["id"],
        venue["id"],
        event_at="2026-12-10T02:00:00.000Z",
        load_in_at="2026-12-09T14:00:00.000Z",
        load_out_at="2026-12-10T08:00:00.000Z",
        announce_at="2026-08-26T15:00:00.000Z",
        venue_arrangement="RENTAL",
        rental_fee_cents=80_000,
    )
    tier = build.tier(show["id"], tier_name="GA", price_cents=4_000, allocation_qty=400)
    return {
        "market": market,
        "artist": artist,
        "venue": venue,
        "show": show,
        "tier": tier,
    }


def _orphan_show_payload(world, **overrides):
    payload = {
        "artist_id": world["artist"]["id"],
        "venue_id": world["venue"]["id"],
        "event_at": "2026-12-17T02:00:00.000Z",
        "load_in_at": "2026-12-16T14:00:00.000Z",
        "load_out_at": "2026-12-17T08:00:00.000Z",
        "announce_at": "2026-08-26T15:00:00.000Z",
        "venue_arrangement": "RENTAL",
        "rental_fee_cents": 80_000,
    }
    payload.update(overrides)
    return payload


def _cross_reference_world(build):
    """Two dates at one building, each carrying its own production line."""
    market = build.market(
        name="Coherence Market",
        region_code="COH",
        guarantee_exposure_limit_cents=6_000_000,
    )
    venue = build.venue(
        market["id"],
        name="Coherence Hall",
        gross_capacity=800,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
    )
    artist_a = build.artist(
        name="Coherence Act A",
        agency="Coh Talent",
        tier="CLUB",
        historical_sellthrough_pct=50.00,
    )
    artist_b = build.artist(
        name="Coherence Act B",
        agency="Coh Talent",
        tier="CLUB",
        historical_sellthrough_pct=50.00,
    )
    show_a = build.show(
        artist_a["id"],
        venue["id"],
        event_at="2026-12-04T02:00:00.000Z",
        load_in_at="2026-12-03T14:00:00.000Z",
        load_out_at="2026-12-04T08:00:00.000Z",
        announce_at="2026-08-26T15:00:00.000Z",
        venue_arrangement="RENTAL",
        rental_fee_cents=70_000,
    )
    show_b = build.show(
        artist_b["id"],
        venue["id"],
        event_at="2026-12-08T02:00:00.000Z",
        load_in_at="2026-12-07T14:00:00.000Z",
        load_out_at="2026-12-08T08:00:00.000Z",
        announce_at="2026-08-26T15:00:00.000Z",
        venue_arrangement="RENTAL",
        rental_fee_cents=70_000,
    )
    line_a = build.budget_line(
        show_a["id"],
        category="PRODUCTION",
        description="A-side risers",
        budgeted_cents=250_000,
    )
    line_b = build.budget_line(
        show_b["id"],
        category="PRODUCTION",
        description="B-side risers",
        budgeted_cents=250_000,
    )
    return {
        "market": market,
        "venue": venue,
        "show_a": show_a,
        "show_b": show_b,
        "line_a": line_a,
        "line_b": line_b,
    }

# ---------------------------------------------------------------------------
# Market creation: every derived field at its declared birth value
# ---------------------------------------------------------------------------


def test_market_creation_returns_201_with_its_inputs_echoed(api, build):
    """PRD §3.1: "The creation payload supplies a `name` of between 1 and 120 characters, a
    `region_code` of between 2 and 8 uppercase characters used on reports, and
    `guarantee_exposure_limit_cents`, an integer of at least 1 that is the hard ceiling on the
    artist guarantees this market may carry outstanding at any one moment."

    PRD §4: "Resource creation endpoints return HTTP 201 with the created object in `data`"

    Design: Corner/entities/market_creation_returns_201_with_every_computed_field_at_its_declared_default
    """
    payload = {
        "name": "Mid-Atlantic",
        "region_code": "MATL",
        "guarantee_exposure_limit_cents": 8_000_000,
    }

    market = validate_success(api.create_market(payload, build.risk), 201)

    assert market["name"] == "Mid-Atlantic"
    assert market["region_code"] == "MATL"
    assert market["guarantee_exposure_limit_cents"] == 8_000_000


def test_market_creation_sets_every_derived_field_to_its_empty_value(api, build):
    """PRD §3.1: "A newly opened market starts empty in every derived respect:
    `committed_guarantee_cents` 0, `at_risk_guarantee_cents` 0, `exposure_utilization_pct` 0,
    `risk_posture` `OPEN`, `settled_show_count` 0, and `performance_index` 0."

    Design: Corner/entities/market_creation_returns_201_with_every_computed_field_at_its_declared_default
    """
    payload = {
        "name": "Mid-Atlantic",
        "region_code": "MATL",
        "guarantee_exposure_limit_cents": 8_000_000,
    }

    market = validate_success(api.create_market(payload, build.risk), 201)

    assert market["committed_guarantee_cents"] == 0
    assert market["at_risk_guarantee_cents"] == 0
    assert float(market["exposure_utilization_pct"]) == pytest.approx(0, abs=0.01)
    assert market["risk_posture"] == "OPEN"
    assert market["settled_show_count"] == 0
    assert float(market["performance_index"]) == pytest.approx(0, abs=0.01)


def test_market_creation_bands_an_unused_limit_as_open(api, build):
    """PRD §3.3: "`risk_posture` is then banded from that **rounded** percentage: `OPEN` when it is
    at most 70, `WATCH` when it is greater than 70 and at most 90, `RESTRICTED` when it is greater
    than 90 and strictly below 100, and `FROZEN` at 100 or above."

    Design: Corner/entities/market_creation_returns_201_with_every_computed_field_at_its_declared_default
    """
    payload = {
        "name": "Mountain West",
        "region_code": "MTW",
        "guarantee_exposure_limit_cents": 4_000_000,
    }

    market = validate_success(api.create_market(payload, build.risk), 201)

    assert float(market["exposure_utilization_pct"]) == pytest.approx(0, abs=0.01)
    assert market["risk_posture"] == "OPEN"


def test_market_creation_mints_a_bare_uuid_at_version_one(api, build):
    """PRD §2.4: "Every persisted resource carries an `id` that is a server-minted UUID.
    Identifiers carry no type prefix and are never supplied by the client; a client-supplied `id`
    in a creation body is ignored."

    PRD §2.4: "`version` starts at 1 when the resource is created and increases by exactly 1 on
    each mutation of that resource, and `updated_at` is refreshed to the current logical clock on
    each mutation."

    Design: Corner/entities/market_creation_returns_201_with_every_computed_field_at_its_declared_default
    """
    payload = {
        "name": "Mid-Atlantic",
        "region_code": "MATL",
        "guarantee_exposure_limit_cents": 8_000_000,
    }

    market = validate_success(api.create_market(payload, build.risk), 201)

    assert_common_fields(market, expected_version=1)
    assert is_valid_uuid(market["id"])
    assert_millisecond_precision(market["created_at"])
    assert_millisecond_precision(market["updated_at"])
    # No mutation has happened yet, so the refreshed stamp is still the creation stamp.
    assert_timestamp_equals(market["updated_at"], market["created_at"])


# ---------------------------------------------------------------------------
# Reading a show back: the stored row, including the copied market
# ---------------------------------------------------------------------------


def test_get_show_returns_the_market_id_copied_from_its_venue(api, build):
    """PRD §3.1: "the server copies the venue's market into the show's own `market_id` at creation
    and never re-derives it afterwards — moving a venue between markets later does not move its
    already-booked shows."

    Design: Corner/entities/get_show_returns_the_stored_row_including_the_system_copied_market_id
    """
    world = _stored_show_world(build)

    response = api.get_show(world["show"]["id"], build.accountant)
    show = validate_success(response, 200)

    assert show["id"] == world["show"]["id"]
    assert show["market_id"] == world["market"]["id"]
    assert show["venue_id"] == world["venue"]["id"]
    assert show["artist_id"] == world["artist"]["id"]
    assert_no_pagination_meta(response.json())


def test_get_show_echoes_its_stored_copromote_terms(api, build):
    """PRD §3.1: "Under `CO_PROMOTE` the building reimburses declared shares of the promoter's
    expense and takes a percentage of promoter net: `copromote_venue_share_pct` is required, must be
    greater than 0, and lies between 0.00 and 50.00 with two decimals, while `rental_fee_cents` must
    be 0 and each of the four category percentages lies between 0.00 and 100.00 with two decimals"

    Design: Corner/entities/get_show_returns_the_stored_row_including_the_system_copied_market_id
    """
    world = _stored_show_world(build)

    show = validate_success(api.get_show(world["show"]["id"], build.accountant), 200)

    assert show["venue_arrangement"] == "CO_PROMOTE"
    assert float(show["copromote_venue_share_pct"]) == pytest.approx(12.50, abs=0.01)
    assert show["rental_fee_cents"] == 0
    assert float(show["venue_expense_pct_production"]) == pytest.approx(40.00, abs=0.01)
    assert float(show["venue_expense_pct_marketing"]) == pytest.approx(0, abs=0.01)
    assert float(show["venue_expense_pct_staffing"]) == pytest.approx(0, abs=0.01)
    assert float(show["venue_expense_pct_hospitality"]) == pytest.approx(0, abs=0.01)


def test_newly_booked_show_reads_back_planned_and_pre_sale(api, build):
    """PRD §3.1: "A newly booked show starts in `show_status` `PLANNED` and `sales_status`
    `PRE_SALE`, commits no guarantee, and contributes nothing to its market's exposure."

    PRD §3.1: "A replacement date created for a postponed original additionally names the original
    in `rescheduled_from_show_id`; on every other show that field is null."

    PRD §3.6: "It is `ON_BUDGET` when every one of the show's lines is `WITHIN_TOLERANCE`"

    Design: Corner/entities/get_show_returns_the_stored_row_including_the_system_copied_market_id
    """
    world = _stored_show_world(build)

    show = validate_success(api.get_show(world["show"]["id"], build.accountant), 200)

    assert show["show_status"] == "PLANNED"
    assert show["sales_status"] == "PRE_SALE"
    assert show["rescheduled_from_show_id"] is None
    assert show["budget_posture"] == "ON_BUDGET"
    assert_common_fields(show, expected_version=1)


def test_newly_booked_show_reads_back_with_every_rollup_at_zero(api, build):
    """PRD §3.3: "The show's `committed_guarantee_cents` is set to the accepted offer's
    `guarantee_cents` — this field is defined as the guarantee of the single offer on the show whose
    status is `ACCEPTED`, and 0 when no such offer exists."

    PRD §3.6: "While no offer on the show is `ACCEPTED`, the show's `breakeven_cents` is 0."

    PRD §3.6: "A show's `total_budgeted_expense_cents` is the sum of `budgeted_cents` over its lines
    whose `status` is not `VOID`, and its `total_actual_expense_cents` is the sum of `actual_cents`
    over the same set — the invoiced reality."

    PRD §3.4: "The show's `gross_sold_cents` is the sum of `gross_sold_cents` across **its own**
    tiers, and its `paid_tickets_sold` is the sum of `sold_qty` across its own tiers"

    Design: Corner/entities/get_show_returns_the_stored_row_including_the_system_copied_market_id
    """
    world = _stored_show_world(build)

    show = validate_success(api.get_show(world["show"]["id"], build.accountant), 200)

    assert show["committed_guarantee_cents"] == 0
    assert show["breakeven_cents"] == 0
    assert show["gross_sold_cents"] == 0
    assert show["paid_tickets_sold"] == 0
    assert show["comp_tickets_issued"] == 0
    assert show["held_tickets"] == 0
    assert show["total_budgeted_expense_cents"] == 0
    assert show["total_actual_expense_cents"] == 0


# ---------------------------------------------------------------------------
# Listing shows: filters, then counting, then the page window
# ---------------------------------------------------------------------------


def test_list_shows_unpaged_returns_every_row_under_the_default_limit(api, build):
    """PRD §2.3: "`limit` controls page size: it defaults to 10, may not be smaller than 1, and may
    not be larger than 100."

    PRD §2.3: "List results are ordered by `created_at` ascending — oldest first — unless a specific
    endpoint's description in §4 states otherwise."

    Design: Corner/entities/list_shows_filters_by_show_status_and_paginates_with_total_count_and_has_more
    """
    world = _show_index_world(build)

    data, meta = validate_paginated(api.list_shows(build.risk))

    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 5
    assert meta["has_more"] is False
    assert len(data) == 5
    assert {row["id"] for row in data} == {show["id"] for show in world["shows"]}
    assert_created_at_ascending(data)
    for row in data:
        assert row["show_status"] in {"PLANNED", "CONFIRMED"}
        assert row["sales_status"] == "PRE_SALE"


def test_list_shows_counts_the_filtered_set_before_paginating(api, build):
    """PRD §2.3: "`total_count` (the number of records matching the filters before pagination), and
    `has_more` (true when records remain beyond the current page)."

    PRD §3.1: "Shows may be listed and narrowed by any of `market_id`, `artist_id`, `venue_id`,
    `rescheduled_from_show_id`, `show_status` and `sales_status`."

    Design: Corner/entities/list_shows_filters_by_show_status_and_paginates_with_total_count_and_has_more
    """
    world = _show_index_world(build)
    confirmed_ids = {show["id"] for show in world["shows"][:3]}

    first_data, first_meta = validate_paginated(
        api.list_shows(build.risk, show_status="CONFIRMED", limit=2, offset=0)
    )
    second_data, second_meta = validate_paginated(
        api.list_shows(build.risk, show_status="CONFIRMED", limit=2, offset=2)
    )

    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert len(first_data) == 2

    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert len(second_data) == 1

    paged_ids = [row["id"] for row in first_data] + [row["id"] for row in second_data]
    assert len(set(paged_ids)) == 3
    assert set(paged_ids) == confirmed_ids
    for row in first_data + second_data:
        assert row["show_status"] == "CONFIRMED"


def test_list_shows_composes_a_venue_filter_with_a_status_filter(api, build):
    """PRD §3.1: "Shows may be listed and narrowed by any of `market_id`, `artist_id`, `venue_id`,
    `rescheduled_from_show_id`, `show_status` and `sales_status`."

    Design: Corner/entities/list_shows_filters_by_show_status_and_paginates_with_total_count_and_has_more
    """
    world = _show_index_world(build)
    planned_ids = {show["id"] for show in world["shows"][3:]}

    data, meta = validate_paginated(
        api.list_shows(build.risk, venue_id=world["venue"]["id"], show_status="PLANNED")
    )

    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert {row["id"] for row in data} == planned_ids
    for row in data:
        assert row["show_status"] == "PLANNED"
        assert row["venue_id"] == world["venue"]["id"]


# ---------------------------------------------------------------------------
# Unknown identifiers: one error id per entity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "resource_key,reader",
    [
        ("market", "get_market"),
        ("artist", "get_artist"),
        ("venue", "get_venue"),
        ("show", "get_show"),
        ("offer", "get_offer"),
        ("budget_line", "get_budget_line"),
        ("vendor_invoice", "get_vendor_invoice"),
        ("ticket_tier", "get_ticket_tier"),
        ("ticket_hold", "get_ticket_hold"),
        ("settlement", "get_settlement"),
        ("cancellation_event", "get_cancellation_event"),
    ],
)
def test_unknown_id_returns_the_entity_specific_not_found_error(api, build, resource_key, reader):
    """PRD §2.11: "The variables and their codes are: `market_id` → `ERR_MARKET_NOT_FOUND`,
    `artist_id` → `ERR_ARTIST_NOT_FOUND`, `venue_id` → `ERR_VENUE_NOT_FOUND`, `show_id` →
    `ERR_SHOW_NOT_FOUND`, `offer_id` → `ERR_OFFER_NOT_FOUND`, `budget_line_id` →
    `ERR_BUDGET_LINE_NOT_FOUND`, `vendor_invoice_id` → `ERR_VENDOR_INVOICE_NOT_FOUND`,
    `ticket_tier_id` → `ERR_TICKET_TIER_NOT_FOUND`, `ticket_hold_id` →
    `ERR_TICKET_HOLD_NOT_FOUND`, `settlement_id` → `ERR_SETTLEMENT_NOT_FOUND`, and
    `cancellation_event_id` → `ERR_CANCELLATION_EVENT_NOT_FOUND`. All eleven are HTTP 404."

    Design: Corner/entities/unknown_uuids_return_the_entity_specific_not_found_error_id
    """
    expected_error_id = E.NOT_FOUND_BY_RESOURCE[resource_key]

    response = getattr(api, reader)(UNALLOCATED_UUID, build.risk)

    validate_error(response, expected_error_id, 404)


def test_unknown_id_error_uses_the_standard_error_envelope(api, build):
    """PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific
    error."

    PRD §2.11: "All eleven are HTTP 404."

    Design: Corner/entities/unknown_uuids_return_the_entity_specific_not_found_error_id
    """
    response = api.get_show(UNALLOCATED_UUID, build.risk)

    validate_error(response, E.ERR_SHOW_NOT_FOUND, 404)
    body = response.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == E.ERR_SHOW_NOT_FOUND
    assert isinstance(body["data"].get("message"), str) and body["data"]["message"]


# ---------------------------------------------------------------------------
# Offer creation: a missing required input is malformed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "omitted_field",
    ["show_id", "deal_structure", "guarantee_cents", "deposit_cents"],
)
def test_offer_creation_omitting_a_required_deal_term_is_rejected(api, build, omitted_field):
    """PRD §2.9: "Request-body well-formedness — `ERR_INVALID_REQUEST`. Every required field must be
    present, every enum-valued field must hold a declared member, every `_cents` field must be an
    integer that is not negative"

    PRD §3.2: "It names its show by `show_id` and carries the deal terms: a `deal_structure` that is
    one of `FLAT_GUARANTEE`, `VERSUS` or `GUARANTEE_PLUS_BACKEND`; a `guarantee_cents` of at least 1,
    the floor the promoter owes regardless of what the box office does; a `deposit_cents` of 0 or
    more, wired at confirmation and credited back at settlement"

    Design: Corner/entities/offer_creation_with_any_required_input_omitted_is_rejected
    """
    world = _required_fields_world(build)
    payload = _full_offer_payload(world["show"])
    payload.pop(omitted_field)

    response = api.create_offer(payload, build.buyer)

    validate_error(response, E.ERR_INVALID_REQUEST, 400)


def test_offer_creation_omitting_expected_show_version_is_rejected(api, build):
    """PRD §2.7: "Both therefore require the client to prove that its view of the parent `Show` is
    current, by supplying `expected_show_version` — a non-optional integer field in the request body
    carrying the client's last observed `version` of that show."

    Design: Corner/entities/offer_creation_with_any_required_input_omitted_is_rejected
    """
    world = _required_fields_world(build)
    payload = _full_offer_payload(world["show"])
    payload.pop("expected_show_version")

    response = api.create_offer(payload, build.buyer)

    validate_error(response, E.ERR_INVALID_REQUEST, 400)


def test_offer_creation_with_every_required_term_present_succeeds(api, build):
    """PRD §3.2: "Two conditional terms complete the structure: `versus_pct`, the artist's
    percentage of net-after-expenses, and `backend_split_artist_pct`, the artist's percentage of
    gross above breakeven; each lies between 0.00 and 100.00 with two decimals and each defaults
    to 0."

    PRD §3.2: "On success the new offer is created in status `DRAFT` with `round_index` 1"

    Design: Corner/entities/offer_creation_with_any_required_input_omitted_is_rejected
    """
    world = _required_fields_world(build)

    offer = validate_success(
        api.create_offer(_full_offer_payload(world["show"]), build.buyer), 201
    )

    assert offer["show_id"] == world["show"]["id"]
    assert offer["deal_structure"] == "FLAT_GUARANTEE"
    assert offer["guarantee_cents"] == 2_000_000
    assert offer["deposit_cents"] == 0
    assert float(offer["versus_pct"]) == pytest.approx(0, abs=0.01)
    assert float(offer["backend_split_artist_pct"]) == pytest.approx(0, abs=0.01)
    assert offer["status"] == "DRAFT"
    assert offer["round_index"] == 1


def test_malformed_offer_bodies_persist_no_offer_row(api, build):
    """PRD §2.9: "No later rule is evaluated once one has fired, and no side effect of the operation
    runs."

    Design: Corner/entities/offer_creation_with_any_required_input_omitted_is_rejected
    """
    world = _required_fields_world(build)
    for omitted_field in (
        "show_id",
        "expected_show_version",
        "deal_structure",
        "guarantee_cents",
        "deposit_cents",
    ):
        payload = _full_offer_payload(world["show"])
        payload.pop(omitted_field)
        validate_error(api.create_offer(payload, build.buyer), E.ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(api.list_offers(build.buyer, show_id=world["show"]["id"]))

    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Omitted optional inputs fall back to their declared defaults
# ---------------------------------------------------------------------------


def test_artist_omitting_withholding_pct_defaults_it_to_zero(api, build):
    """PRD §3.1: "and an optional `withholding_pct` between 0.00 and 40.00 with two decimals, the
    statutory rate deducted from the act's earnings at settlement — omit it and it defaults to 0.
    The act's `confirmed_show_count` starts at 0 and tracks how many of its shows currently sit in
    the `CONFIRMED`, `ON_SALE` or `PERFORMED` window."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
    """
    payload = {
        "name": "Default Act",
        "agency": "Def Talent",
        "tier": "CLUB",
        "historical_sellthrough_pct": 55.00,
    }

    artist = validate_success(api.create_artist(payload, build.buyer), 201)

    assert float(artist["withholding_pct"]) == pytest.approx(0, abs=0.01)
    assert artist["confirmed_show_count"] == 0
    assert float(artist["historical_sellthrough_pct"]) == pytest.approx(55.00, abs=0.01)


def test_rental_show_venue_percentages_are_all_zero(api, build):
    """PRD §3.1: "Under `RENTAL` the promoter bears every expense and the building takes a flat fee:
    `rental_fee_cents` is required and must be greater than 0, while `copromote_venue_share_pct`,
    `venue_expense_pct_production`, `venue_expense_pct_marketing`, `venue_expense_pct_staffing` and
    `venue_expense_pct_hospitality` must all be 0."

    PRD §3.1: "on every other show that field is null."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
    """
    world = _defaults_world(build)
    artist = build.artist(
        name="Default Act", agency="Def Talent", tier="CLUB", historical_sellthrough_pct=55.00
    )
    payload = {
        "artist_id": artist["id"],
        "venue_id": world["venue"]["id"],
        "event_at": "2026-11-12T02:00:00.000Z",
        "load_in_at": "2026-11-11T14:00:00.000Z",
        "load_out_at": "2026-11-12T08:00:00.000Z",
        "announce_at": "2026-08-18T15:00:00.000Z",
        "venue_arrangement": "RENTAL",
        "rental_fee_cents": 90_000,
    }

    show = validate_success(api.create_show(payload, build.buyer), 201)

    assert show["rental_fee_cents"] == 90_000
    assert float(show["copromote_venue_share_pct"]) == pytest.approx(0, abs=0.01)
    assert float(show["venue_expense_pct_production"]) == pytest.approx(0, abs=0.01)
    assert float(show["venue_expense_pct_marketing"]) == pytest.approx(0, abs=0.01)
    assert float(show["venue_expense_pct_staffing"]) == pytest.approx(0, abs=0.01)
    assert float(show["venue_expense_pct_hospitality"]) == pytest.approx(0, abs=0.01)
    assert show["rescheduled_from_show_id"] is None


def test_budget_line_omitting_is_artist_deductible_defaults_it_to_false(api, build):
    """PRD §3.6: "an optional `is_artist_deductible` boolean declaring whether the line may enter
    the artist's deductible expense base at settlement. Omit `is_artist_deductible` and it defaults
    to false."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
    """
    world = _defaults_world(build)
    _, show = _defaults_show(build, world)
    payload = {
        "show_id": show["id"],
        "category": "PRODUCTION",
        "description": "Stage package",
        "budgeted_cents": 400_000,
    }

    line = validate_success(api.create_budget_line(payload, build.accountant), 201)

    assert line["is_artist_deductible"] is False
    assert line["budgeted_cents"] == 400_000
    assert line["category"] == "PRODUCTION"


def test_budget_line_is_created_with_its_whole_variance_block_empty(api, build):
    """PRD §3.6: "A new line is created with `actual_cents` 0, `variance_cents` 0, `variance_pct` 0,
    `variance_status` `WITHIN_TOLERANCE`, `required_approver_role` `NONE`, `approved_cap_cents` null,
    `variance_decided_by_user_id` null, `variance_justification` null, `settlement_expense_cents` 0,
    and lifecycle `status` `ACTIVE`."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
    """
    world = _defaults_world(build)
    _, show = _defaults_show(build, world)
    payload = {
        "show_id": show["id"],
        "category": "MARKETING",
        "description": "Radio spots",
        "budgeted_cents": 150_000,
    }

    line = validate_success(api.create_budget_line(payload, build.accountant), 201)

    assert line["actual_cents"] == 0
    assert line["variance_cents"] == 0
    assert float(line["variance_pct"]) == pytest.approx(0, abs=0.01)
    assert line["variance_status"] == "WITHIN_TOLERANCE"
    assert line["required_approver_role"] == "NONE"
    assert line["approved_cap_cents"] is None
    assert line["variance_decided_by_user_id"] is None
    assert line["variance_justification"] is None
    assert line["settlement_expense_cents"] == 0
    assert line["status"] == "ACTIVE"


def test_ticket_tier_is_born_draft_with_every_seat_available(api, build):
    """PRD §3.4: "A new tier is born in status `DRAFT` with `sold_qty` 0, `gross_sold_cents` 0,
    `comp_qty` 0, `held_qty` 0, `available_qty` equal to its `allocation_qty`,
    `price_revision_count` 0 and `last_price_cents` null."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
    """
    world = _defaults_world(build)
    _, show = _defaults_show(build, world)
    payload = {
        "show_id": show["id"],
        "tier_name": "GA",
        "price_cents": 5_000,
        "allocation_qty": 600,
    }

    tier = validate_success(api.create_ticket_tier(payload, build.buyer), 201)

    assert tier["status"] == "DRAFT"
    assert tier["sold_qty"] == 0
    assert tier["gross_sold_cents"] == 0
    assert tier["comp_qty"] == 0
    assert tier["held_qty"] == 0
    assert tier["available_qty"] == 600
    assert tier["available_qty"] == tier["allocation_qty"]
    assert tier["price_revision_count"] == 0
    assert tier["last_price_cents"] is None


def test_ticket_hold_is_created_held_with_no_releasing_user(api, build):
    """PRD §3.5: "A hold is created in status `HELD` with `released_by_user_id` null."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
    """
    world = _defaults_world(build)
    _, show = _defaults_show(build, world)
    tier = build.tier(show["id"], tier_name="GA", price_cents=5_000, allocation_qty=600)
    payload = {
        "ticket_tier_id": tier["id"],
        "kind": "PRODUCTION_HOLD",
        "qty": 20,
        "holder": "Front of house mix",
    }

    hold = validate_success(api.create_ticket_hold(payload, build.buyer), 201)

    assert hold["status"] == "HELD"
    assert hold["released_by_user_id"] is None
    assert hold["kind"] == "PRODUCTION_HOLD"
    assert hold["qty"] == 20


def test_hold_creation_moves_seats_out_of_the_available_count(api, build):
    """PRD §3.5: "On success, a `COMP` hold increases the tier's `comp_qty` by the held quantity
    while every other kind increases the tier's `held_qty`, and either way the tier's
    `available_qty` decreases by the same quantity."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
    """
    world = _defaults_world(build)
    _, show = _defaults_show(build, world)
    tier = build.tier(show["id"], tier_name="GA", price_cents=5_000, allocation_qty=600)
    build.hold(tier["id"], kind="PRODUCTION_HOLD", qty=20, holder="Front of house mix")

    refreshed = validate_success(api.get_ticket_tier(tier["id"], build.buyer), 200)

    assert refreshed["held_qty"] == 20
    assert refreshed["comp_qty"] == 0
    assert refreshed["available_qty"] == 580
    assert_tier_inventory_conserved(refreshed)


# ---------------------------------------------------------------------------
# Client-supplied computed money fields are treated as input, not as truth
# ---------------------------------------------------------------------------


def test_market_creation_ignores_supplied_exposure_figures(api, build):
    """PRD §3.1: "A newly opened market starts empty in every derived respect:
    `committed_guarantee_cents` 0, `at_risk_guarantee_cents` 0, `exposure_utilization_pct` 0,
    `risk_posture` `OPEN`, `settled_show_count` 0, and `performance_index` 0."

    Design: Corner/entities/client_supplied_computed_money_fields_are_ignored_input
    """
    payload = {
        "name": "Poisoned Market",
        "region_code": "PSN",
        "guarantee_exposure_limit_cents": 4_000_000,
        "committed_guarantee_cents": 3_999_999,
        "at_risk_guarantee_cents": 12_345,
        "exposure_utilization_pct": 99.99,
        "risk_posture": "FROZEN",
        "settled_show_count": 77,
        "performance_index": 250,
    }

    market = validate_success(api.create_market(payload, build.risk), 201)

    assert market["committed_guarantee_cents"] == 0
    assert market["at_risk_guarantee_cents"] == 0
    assert float(market["exposure_utilization_pct"]) == pytest.approx(0, abs=0.01)
    assert market["risk_posture"] == "OPEN"
    assert market["settled_show_count"] == 0
    assert float(market["performance_index"]) == pytest.approx(0, abs=0.01)
    assert market["guarantee_exposure_limit_cents"] == 4_000_000


def test_artist_creation_ignores_a_supplied_confirmed_show_count(api, build):
    """PRD §3.1: "The act's `confirmed_show_count` starts at 0 and tracks how many of its shows
    currently sit in the `CONFIRMED`, `ON_SALE` or `PERFORMED` window."

    Design: Corner/entities/client_supplied_computed_money_fields_are_ignored_input
    """
    payload = {
        "name": "Poisoned Act",
        "agency": "Psn Talent",
        "tier": "ARENA",
        "historical_sellthrough_pct": 70.00,
        "withholding_pct": 10.00,
        "confirmed_show_count": 42,
    }

    artist = validate_success(api.create_artist(payload, build.buyer), 201)

    assert artist["confirmed_show_count"] == 0
    assert float(artist["withholding_pct"]) == pytest.approx(10.00, abs=0.01)


def test_show_creation_ignores_supplied_box_office_and_budget_rollups(api, build):
    """PRD §3.3: "The show's `committed_guarantee_cents` is set to the accepted offer's
    `guarantee_cents` — this field is defined as the guarantee of the single offer on the show whose
    status is `ACCEPTED`, and 0 when no such offer exists."

    PRD §3.6: "While no offer on the show is `ACCEPTED`, the show's `breakeven_cents` is 0."

    PRD §3.4: "The show's `gross_sold_cents` is the sum of `gross_sold_cents` across **its own**
    tiers, and its `paid_tickets_sold` is the sum of `sold_qty` across its own tiers"

    PRD §3.6: "It is `ON_BUDGET` when every one of the show's lines is `WITHIN_TOLERANCE`"

    Design: Corner/entities/client_supplied_computed_money_fields_are_ignored_input
    """
    world = _defaults_world(build)
    artist = build.artist(
        name="Poisoned Act", agency="Psn Talent", tier="CLUB", historical_sellthrough_pct=55.00
    )
    payload = {
        "artist_id": artist["id"],
        "venue_id": world["venue"]["id"],
        "event_at": "2026-11-19T02:00:00.000Z",
        "load_in_at": "2026-11-18T14:00:00.000Z",
        "load_out_at": "2026-11-19T08:00:00.000Z",
        "announce_at": "2026-08-18T15:00:00.000Z",
        "venue_arrangement": "RENTAL",
        "rental_fee_cents": 90_000,
        "committed_guarantee_cents": 7_777_777,
        "breakeven_cents": 6_666_666,
        "gross_sold_cents": 5_555_555,
        "paid_tickets_sold": 4_444,
        "budget_posture": "OVER_BUDGET",
    }

    show = validate_success(api.create_show(payload, build.buyer), 201)

    assert show["committed_guarantee_cents"] == 0
    assert show["breakeven_cents"] == 0
    assert show["gross_sold_cents"] == 0
    assert show["paid_tickets_sold"] == 0
    assert show["budget_posture"] == "ON_BUDGET"


def test_ticket_tier_creation_ignores_supplied_inventory_counters(api, build):
    """PRD §3.4: "A new tier is born in status `DRAFT` with `sold_qty` 0, `gross_sold_cents` 0,
    `comp_qty` 0, `held_qty` 0, `available_qty` equal to its `allocation_qty`,
    `price_revision_count` 0 and `last_price_cents` null."

    Design: Corner/entities/client_supplied_computed_money_fields_are_ignored_input
    """
    world = _defaults_world(build)
    _, show = _defaults_show(build, world)
    payload = {
        "show_id": show["id"],
        "tier_name": "PIT",
        "price_cents": 6_000,
        "allocation_qty": 500,
        "sold_qty": 499,
        "gross_sold_cents": 2_994_000,
        "comp_qty": 1,
        "held_qty": 0,
        "available_qty": 0,
        "price_revision_count": 9,
        "last_price_cents": 1,
        "status": "CLOSED",
    }

    tier = validate_success(api.create_ticket_tier(payload, build.buyer), 201)

    assert tier["status"] == "DRAFT"
    assert tier["sold_qty"] == 0
    assert tier["gross_sold_cents"] == 0
    assert tier["comp_qty"] == 0
    assert tier["held_qty"] == 0
    assert tier["available_qty"] == 500
    assert tier["price_revision_count"] == 0
    assert tier["last_price_cents"] is None
    assert_tier_inventory_conserved(tier)


def test_budget_line_creation_ignores_supplied_actuals(api, build):
    """PRD §3.6: "A new line is created with `actual_cents` 0, `variance_cents` 0, `variance_pct` 0,
    `variance_status` `WITHIN_TOLERANCE`, `required_approver_role` `NONE`, `approved_cap_cents` null,
    `variance_decided_by_user_id` null, `variance_justification` null, `settlement_expense_cents` 0,
    and lifecycle `status` `ACTIVE`."

    Design: Corner/entities/client_supplied_computed_money_fields_are_ignored_input
    """
    world = _defaults_world(build)
    _, show = _defaults_show(build, world)
    payload = {
        "show_id": show["id"],
        "category": "STAFFING",
        "description": "Local crew calls",
        "budgeted_cents": 300_000,
        "actual_cents": 299_000,
        "settlement_expense_cents": 299_000,
        "variance_status": "APPROVED",
        "required_approver_role": "RiskOfficer",
        "status": "VOID",
    }

    line = validate_success(api.create_budget_line(payload, build.accountant), 201)

    assert line["budgeted_cents"] == 300_000
    assert line["actual_cents"] == 0
    assert line["variance_cents"] == 0
    assert line["settlement_expense_cents"] == 0
    assert line["variance_status"] == "WITHIN_TOLERANCE"
    assert line["required_approver_role"] == "NONE"
    assert line["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Client-supplied identity, status and audit fields are input, not authority
# ---------------------------------------------------------------------------


def test_show_creation_mints_its_own_id_and_ignores_the_supplied_one(api, build):
    """PRD §2.4: "Every persisted resource carries an `id` that is a server-minted UUID. Identifiers
    carry no type prefix and are never supplied by the client; a client-supplied `id` in a creation
    body is ignored."

    Design: Corner/entities/client_supplied_identity_and_audit_fields_are_ignored_input
    """
    world = _system_fields_world(build)

    show = validate_success(api.create_show(_forged_show_payload(world), build.buyer), 201)

    assert show["id"] != FORGED_UUID
    assert is_valid_uuid(show["id"])
    assert show.get("exposure_override_limit_cents") != 999_999_999
    assert show.get("exposure_override_by_user_id") != "u_forged"
    # The minted id is the one the row is addressable by.
    reread = validate_success(api.get_show(show["id"], build.buyer), 200)
    assert reread["id"] == show["id"]


def test_show_market_id_is_derived_from_the_venue_not_from_the_body(api, build):
    """PRD §3.1: "the server copies the venue's market into the show's own `market_id` at creation
    and never re-derives it afterwards — moving a venue between markets later does not move its
    already-booked shows."

    Design: Corner/entities/client_supplied_identity_and_audit_fields_are_ignored_input
    """
    world = _system_fields_world(build)

    show = validate_success(api.create_show(_forged_show_payload(world), build.buyer), 201)

    assert show["market_id"] == world["true_market"]["id"]
    assert show["market_id"] != world["decoy_market"]["id"]
    decoy = validate_success(api.get_market(world["decoy_market"]["id"], build.risk), 200)
    assert decoy["committed_guarantee_cents"] == 0


def test_show_creation_ignores_supplied_status_dimensions(api, build):
    """PRD §3.1: "A newly booked show starts in `show_status` `PLANNED` and `sales_status`
    `PRE_SALE`, commits no guarantee, and contributes nothing to its market's exposure."

    Design: Corner/entities/client_supplied_identity_and_audit_fields_are_ignored_input
    """
    world = _system_fields_world(build)

    show = validate_success(api.create_show(_forged_show_payload(world), build.buyer), 201)

    assert show["show_status"] == "PLANNED"
    assert show["sales_status"] == "PRE_SALE"


def test_show_creation_ignores_supplied_version_and_timestamps(api, build):
    """PRD §2.4: "`version` starts at 1 when the resource is created and increases by exactly 1 on
    each mutation of that resource, and `updated_at` is refreshed to the current logical clock on
    each mutation."

    PRD §2.5: "Time in this service is entirely logical. On startup the clock reads exactly
    `2026-08-01T00:00:00Z`, and it never falls back to real wall-clock time under any circumstance."

    Design: Corner/entities/client_supplied_identity_and_audit_fields_are_ignored_input
    """
    world = _system_fields_world(build)

    show = validate_success(api.create_show(_forged_show_payload(world), build.buyer), 201)

    assert show["version"] == 1
    assert_timestamp_equals(show["created_at"], DEFAULT_CLOCK)
    assert_timestamp_equals(show["updated_at"], DEFAULT_CLOCK)
    assert_millisecond_precision(show["created_at"])
    assert_millisecond_precision(show["updated_at"])


def test_offer_creation_ignores_a_supplied_status_and_round_index(api, build):
    """PRD §3.2: "On success the new offer is created in status `DRAFT` with `round_index` 1, and
    every **other** offer on the same show whose status is `SUBMITTED` or `COUNTERED` is moved to
    `SUPERSEDED`."

    PRD §2.4: "`version` starts at 1 when the resource is created and increases by exactly 1 on
    each mutation of that resource"

    Design: Corner/entities/client_supplied_identity_and_audit_fields_are_ignored_input
    """
    world = _system_fields_world(build)
    show = validate_success(api.create_show(_forged_show_payload(world), build.buyer), 201)
    payload = {
        "show_id": show["id"],
        "expected_show_version": show["version"],
        "deal_structure": "FLAT_GUARANTEE",
        "guarantee_cents": 1_500_000,
        "deposit_cents": 0,
        "expense_cap_cents": 500_000,
        "id": FORGED_UUID,
        "status": "ACCEPTED",
        "round_index": 3,
        "version": 12,
    }

    offer = validate_success(api.create_offer(payload, build.buyer), 201)

    assert offer["status"] == "DRAFT"
    assert offer["round_index"] == 1
    assert offer["id"] != FORGED_UUID
    assert offer["version"] == 1


# ---------------------------------------------------------------------------
# Enum membership and numeric ranges
# ---------------------------------------------------------------------------


def test_offer_deal_structure_outside_the_declared_enum_is_rejected(api, build):
    """PRD §2.9: "every enum-valued field must hold a declared member"

    PRD §3.2: "a `deal_structure` that is one of `FLAT_GUARANTEE`, `VERSUS` or
    `GUARANTEE_PLUS_BACKEND`"

    Design: Corner/entities/enum_and_numeric_range_constraints_are_rejected
    """
    world = _type_constraint_world(build)
    payload = _full_offer_payload(world["show"])
    payload["deal_structure"] = "GUARANTEE"

    response = api.create_offer(payload, build.buyer)

    validate_error(response, E.ERR_INVALID_REQUEST, 400)


def test_deposit_above_the_guarantee_is_incoherent_deal_terms(api, build):
    """PRD §3.2: "In every structure `deposit_cents` may not exceed `guarantee_cents`, and
    `expense_cap_cents`, when supplied, must be greater than 0. Any of these violations yields
    `ERR_DEAL_TERMS_INCOHERENT` (HTTP 422)."

    Design: Corner/entities/enum_and_numeric_range_constraints_are_rejected
    """
    world = _type_constraint_world(build)
    payload = _full_offer_payload(world["show"])
    payload["guarantee_cents"] = 1_000_000
    payload["deposit_cents"] = 1_000_001

    response = api.create_offer(payload, build.buyer)

    validate_error(response, E.ERR_DEAL_TERMS_INCOHERENT, 422)


@pytest.mark.parametrize(
    "resource,overrides",
    [
        ("artist", {"withholding_pct": 40.01}),
        ("artist", {"historical_sellthrough_pct": 100.01}),
        ("venue", {"ticket_tax_pct": 25.01}),
        ("venue", {"gross_capacity": 0}),
        ("tier", {"allocation_qty": 0}),
    ],
)
def test_value_outside_its_declared_range_is_rejected(api, build, resource, overrides):
    """PRD §2.9: "every `_pct` field must be a number between 0 and 100 inclusive, every `_at` field
    must be a valid ISO 8601 UTC timestamp, and every quantity field must be an integer of at least
    1."

    PRD §3.1: "a `historical_sellthrough_pct` between 0.00 and 100.00 with two decimals, used when
    projecting; and an optional `withholding_pct` between 0.00 and 40.00 with two decimals"

    PRD §3.1: "a `gross_capacity` of at least 1 seat, a `facility_fee_cents_per_ticket` of 0 or more
    retained by the building on each **paid** ticket (comps never attract it), and a `ticket_tax_pct`
    between 0.00 and 25.00 with two decimals"

    PRD §3.4: "a `price_cents` face price of at least 1, and an `allocation_qty` of at least 1 seat
    — the conserved quantity for that tier."

    Design: Corner/entities/enum_and_numeric_range_constraints_are_rejected
    """
    world = _type_constraint_world(build)

    if resource == "artist":
        payload = {
            "name": "Range Act",
            "agency": "Rng Talent",
            "tier": "CLUB",
            "historical_sellthrough_pct": 50.00,
        }
        payload.update(overrides)
        response = api.create_artist(payload, build.buyer)
    elif resource == "venue":
        payload = {
            "market_id": world["market"]["id"],
            "name": "Range Hall",
            "gross_capacity": 500,
            "facility_fee_cents_per_ticket": 0,
            "ticket_tax_pct": 5.00,
        }
        payload.update(overrides)
        response = api.create_venue(payload, build.buyer)
    else:
        payload = {
            "show_id": world["show"]["id"],
            "tier_name": "GA",
            "price_cents": 5_000,
            "allocation_qty": 100,
        }
        payload.update(overrides)
        response = api.create_ticket_tier(payload, build.buyer)

    validate_error(response, E.ERR_INVALID_REQUEST, 400)


def test_artist_percentages_at_their_inclusive_maxima_are_accepted(api, build):
    """PRD §3.1: "a `historical_sellthrough_pct` between 0.00 and 100.00 with two decimals, used
    when projecting; and an optional `withholding_pct` between 0.00 and 40.00 with two decimals"

    Design: Corner/entities/enum_and_numeric_range_constraints_are_rejected
    """
    payload = {
        "name": "Boundary Act",
        "agency": "Bnd Talent",
        "tier": "HEADLINE",
        "historical_sellthrough_pct": 100.00,
        "withholding_pct": 40.00,
    }

    artist = validate_success(api.create_artist(payload, build.buyer), 201)

    assert float(artist["historical_sellthrough_pct"]) == pytest.approx(100.00, abs=0.01)
    assert float(artist["withholding_pct"]) == pytest.approx(40.00, abs=0.01)


def test_venue_at_its_boundary_capacity_and_tax_is_accepted(api, build):
    """PRD §3.1: "a `gross_capacity` of at least 1 seat, a `facility_fee_cents_per_ticket` of 0 or
    more retained by the building on each **paid** ticket (comps never attract it), and a
    `ticket_tax_pct` between 0.00 and 25.00 with two decimals"

    Design: Corner/entities/enum_and_numeric_range_constraints_are_rejected
    """
    world = _type_constraint_world(build)
    payload = {
        "market_id": world["market"]["id"],
        "name": "Boundary Hall",
        "gross_capacity": 1,
        "facility_fee_cents_per_ticket": 0,
        "ticket_tax_pct": 25.00,
    }

    venue = validate_success(api.create_venue(payload, build.buyer), 201)

    assert venue["gross_capacity"] == 1
    assert float(venue["ticket_tax_pct"]) == pytest.approx(25.00, abs=0.01)


def test_deposit_equal_to_the_guarantee_is_accepted(api, build):
    """PRD §3.2: "In every structure `deposit_cents` may not exceed `guarantee_cents`, and
    `expense_cap_cents`, when supplied, must be greater than 0."

    Design: Corner/entities/enum_and_numeric_range_constraints_are_rejected
    """
    world = _type_constraint_world(build)
    payload = _full_offer_payload(world["show"])
    payload["guarantee_cents"] = 1_000_000
    payload["deposit_cents"] = 1_000_000
    payload["expense_cap_cents"] = 1

    offer = validate_success(api.create_offer(payload, build.buyer), 201)

    assert offer["guarantee_cents"] == 1_000_000
    assert offer["deposit_cents"] == 1_000_000
    assert offer["expense_cap_cents"] == 1


# ---------------------------------------------------------------------------
# Parent identifiers in a body are resolved before anything is written
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "target",
    ["venue_market", "show_artist", "show_venue", "tier_show", "line_show", "hold_tier"],
)
def test_unresolvable_body_identifier_returns_its_own_not_found_error(api, build, target):
    """PRD §2.11: "The same codes apply to identifiers supplied in a request body or as a list filter
    rather than in the path. A body or filter naming a market that does not exist yields
    `ERR_MARKET_NOT_FOUND`; one naming a missing artist yields `ERR_ARTIST_NOT_FOUND`; one naming a
    missing venue yields `ERR_VENUE_NOT_FOUND`."

    PRD §2.11: "A missing `budget_line_id` on an invoice body or filter yields
    `ERR_BUDGET_LINE_NOT_FOUND`, and a missing `ticket_tier_id` on a hold body or filter yields
    `ERR_TICKET_TIER_NOT_FOUND`."

    Design: Corner/entities/parent_foreign_keys_are_resolved_before_creation_and_return_not_found
    """
    world = _parent_fk_world(build)

    if target == "venue_market":
        response = api.create_venue(
            {
                "market_id": UNALLOCATED_UUID,
                "name": "Orphan Hall",
                "gross_capacity": 500,
                "facility_fee_cents_per_ticket": 0,
                "ticket_tax_pct": 0,
            },
            build.buyer,
        )
        expected = E.ERR_MARKET_NOT_FOUND
    elif target == "show_artist":
        response = api.create_show(
            _orphan_show_payload(world, artist_id=UNALLOCATED_UUID), build.buyer
        )
        expected = E.ERR_ARTIST_NOT_FOUND
    elif target == "show_venue":
        response = api.create_show(
            _orphan_show_payload(world, venue_id=UNALLOCATED_UUID), build.buyer
        )
        expected = E.ERR_VENUE_NOT_FOUND
    elif target == "tier_show":
        response = api.create_ticket_tier(
            {
                "show_id": UNALLOCATED_UUID,
                "tier_name": "GA",
                "price_cents": 4_000,
                "allocation_qty": 100,
            },
            build.buyer,
        )
        expected = E.ERR_SHOW_NOT_FOUND
    elif target == "line_show":
        response = api.create_budget_line(
            {
                "show_id": UNALLOCATED_UUID,
                "category": "PRODUCTION",
                "description": "Orphan line",
                "budgeted_cents": 100_000,
            },
            build.accountant,
        )
        expected = E.ERR_SHOW_NOT_FOUND
    else:
        response = api.create_ticket_hold(
            {
                "ticket_tier_id": UNALLOCATED_UUID,
                "kind": "PROMOTER_HOLD",
                "qty": 5,
                "holder": "Orphan holder",
            },
            build.buyer,
        )
        expected = E.ERR_TICKET_TIER_NOT_FOUND

    validate_error(response, expected, 404)


def test_show_creation_resolves_the_artist_before_the_venue(api, build):
    """PRD §2.9: "Existence of every referenced resource, in the order market, artist, venue, show,
    offer, budget line, vendor invoice, ticket tier, ticket hold, settlement, cancellation event —
    each with its own error code, listed in §2.11."

    Design: Corner/entities/parent_foreign_keys_are_resolved_before_creation_and_return_not_found
    """
    world = _parent_fk_world(build)

    response = api.create_show(
        _orphan_show_payload(
            world, artist_id=UNALLOCATED_UUID, venue_id=SECOND_UNALLOCATED_UUID
        ),
        build.buyer,
    )

    validate_error(response, E.ERR_ARTIST_NOT_FOUND, 404)


def test_an_unresolvable_rescheduled_from_show_id_is_still_a_missing_show(api, build):
    """PRD §2.11: "A missing show — whether named as `show_id`, as `rescheduled_from_show_id` at show
    creation, or as `replacement_show_id` at reschedule time — yields `ERR_SHOW_NOT_FOUND`."

    Design: Corner/entities/parent_foreign_keys_are_resolved_before_creation_and_return_not_found
    """
    world = _parent_fk_world(build)

    response = api.create_show(
        _orphan_show_payload(world, rescheduled_from_show_id=UNALLOCATED_UUID), build.buyer
    )

    validate_error(response, E.ERR_SHOW_NOT_FOUND, 404)


def test_creations_with_unresolvable_parents_write_nothing(api, build):
    """PRD §2.9: "No later rule is evaluated once one has fired, and no side effect of the operation
    runs."

    Design: Corner/entities/parent_foreign_keys_are_resolved_before_creation_and_return_not_found
    """
    world = _parent_fk_world(build)

    validate_error(
        api.create_show(_orphan_show_payload(world, artist_id=UNALLOCATED_UUID), build.buyer),
        E.ERR_ARTIST_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_show(_orphan_show_payload(world, venue_id=UNALLOCATED_UUID), build.buyer),
        E.ERR_VENUE_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_show(
            _orphan_show_payload(world, rescheduled_from_show_id=UNALLOCATED_UUID), build.buyer
        ),
        E.ERR_SHOW_NOT_FOUND,
        404,
    )

    _, shows_meta = validate_paginated(api.list_shows(build.risk))
    _, tiers_meta = validate_paginated(api.list_ticket_tiers(build.buyer))

    assert shows_meta["total_count"] == 1
    assert tiers_meta["total_count"] == 1


# ---------------------------------------------------------------------------
# A vendor invoice must name a budget line belonging to its own show
# ---------------------------------------------------------------------------


def test_invoice_naming_a_budget_line_from_another_show_is_rejected(api, build):
    """PRD §3.6: "Cross-reference coherence is enforced: the `BudgetLine` named by `budget_line_id`
    must belong to the same show as the `show_id` on the invoice, or the create is rejected with
    `ERR_BUDGET_LINE_SHOW_MISMATCH` (HTTP 422)."

    Design: Corner/entities/vendor_invoice_cross_reference_integrity_rejects_a_budget_line_from_another_show
    """
    world = _cross_reference_world(build)
    payload = f.vendor_invoice_payload(
        world["show_a"]["id"],
        world["line_b"]["id"],
        amount_cents=120_000,
        vendor_name="Crossed Wires Staging",
    )

    response = api.create_vendor_invoice(payload, build.accountant)

    validate_error(response, E.ERR_BUDGET_LINE_SHOW_MISMATCH, 422)


def test_an_unresolvable_budget_line_is_reported_before_the_mismatch(api, build):
    """PRD §2.9: "Existence of every referenced resource, in the order market, artist, venue, show,
    offer, budget line, vendor invoice, ticket tier, ticket hold, settlement, cancellation event"

    PRD §2.11: "A missing `budget_line_id` on an invoice body or filter yields
    `ERR_BUDGET_LINE_NOT_FOUND`"

    Design: Corner/entities/vendor_invoice_cross_reference_integrity_rejects_a_budget_line_from_another_show
    """
    world = _cross_reference_world(build)
    payload = f.vendor_invoice_payload(
        world["show_a"]["id"],
        UNALLOCATED_UUID,
        amount_cents=120_000,
        vendor_name="Crossed Wires Staging",
    )

    response = api.create_vendor_invoice(payload, build.accountant)

    validate_error(response, E.ERR_BUDGET_LINE_NOT_FOUND, 404)


def test_an_unresolvable_show_is_reported_before_the_mismatch(api, build):
    """PRD §2.9: "Where several rules could reject the same call, they are evaluated in a fixed order
    and the **first** violated rule determines the response."

    PRD §2.11: "A missing show — whether named as `show_id`, as `rescheduled_from_show_id` at show
    creation, or as `replacement_show_id` at reschedule time — yields `ERR_SHOW_NOT_FOUND`."

    Design: Corner/entities/vendor_invoice_cross_reference_integrity_rejects_a_budget_line_from_another_show
    """
    world = _cross_reference_world(build)
    payload = f.vendor_invoice_payload(
        UNALLOCATED_UUID,
        world["line_a"]["id"],
        amount_cents=120_000,
        vendor_name="Crossed Wires Staging",
    )

    response = api.create_vendor_invoice(payload, build.accountant)

    validate_error(response, E.ERR_SHOW_NOT_FOUND, 404)


def test_a_coherent_invoice_is_submitted_and_moves_no_ledger_figure(api, build):
    """PRD §3.6: "The invoice is created in status `SUBMITTED` with `resubmit_count` 0,
    `verified_by_user_id` and `approved_by_user_id` null, and `dispute_reason` null — and pointedly,
    **no** budget line figure moves, because an unapproved invoice is invisible to the ledger."

    Design: Corner/entities/vendor_invoice_cross_reference_integrity_rejects_a_budget_line_from_another_show
    """
    world = _cross_reference_world(build)
    payload = f.vendor_invoice_payload(
        world["show_a"]["id"],
        world["line_a"]["id"],
        amount_cents=120_000,
        vendor_name="Straight Arrow Staging",
    )

    invoice = validate_success(api.create_vendor_invoice(payload, build.accountant), 201)

    assert invoice["show_id"] == world["show_a"]["id"]
    assert invoice["budget_line_id"] == world["line_a"]["id"]
    assert invoice["status"] == "SUBMITTED"
    assert invoice["resubmit_count"] == 0
    assert invoice["verified_by_user_id"] is None
    assert invoice["approved_by_user_id"] is None
    assert invoice["dispute_reason"] is None

    line = validate_success(api.get_budget_line(world["line_a"]["id"], build.accountant), 200)
    assert line["actual_cents"] == 0
    assert line["variance_status"] == "WITHIN_TOLERANCE"
