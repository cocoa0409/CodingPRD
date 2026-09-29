"""Pricing the inventory: rate cards, priced lines, publication and supersession."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_entitlement,
    add_rate_card_line,
    assert_rate_card,
    assert_rate_card_line,
    create_contract,
    create_inventory_asset,
    create_property,
    create_rate_card,
    create_sponsor,
    publish_rate_card,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["property_admin_headers"]
SELLER = TEST_USERS["seller_headers"]


def test_rate_card_line_with_unknown_asset_class_is_rejected(api):
    """PRD §3.2: "The line names its `asset_class` from `SIGNAGE`,
    `DIGITAL_BOARD`, `MEDIA_SPOT`, `HOSPITALITY`, `IP_RIGHTS` and
    `ACTIVATION_SPACE`, and carries a `base_unit_price_cents` of at least 1 as the
    list price per unit before any adjustment."
    PRD §3.2: "Adding a line raises the owning card's `line_count` by 1 and
    increments that card's `version` by 1; the line itself is written once and
    carries neither `updated_at` nor `version`, and it records its owning
    `rate_card_id` from the request path."

    Design: Corner/entities/rate_card_line_invalid_enum_returns_422
    """
    prop = create_property()
    card = create_rate_card(prop["id"])

    response = api.create_rate_card_line(
        card["id"],
        {"asset_class": "BILLBOARD", "base_unit_price_cents": 100_000},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION_FAILED.value)
    assert response.status_code == 422

    reread = validate_success(api.get_rate_card(card["id"], ADMIN))
    assert reread["line_count"] == 0, (
        f"a rejected line must not raise line_count, got {reread['line_count']}"
    )


def test_publishing_a_second_card_supersedes_the_first_and_is_findable_by_pointer(api):
    """PRD §3.2: "A successful publication drives the card `DRAFT → PUBLISHED`,
    stamps `published_at` with the current logical-clock instant, and then
    cascades: the property's previously published card, of which there is at most
    one, is driven `PUBLISHED → SUPERSEDED` and has its
    `superseded_by_rate_card_id` set to the id of the card that just displaced
    it."
    PRD §3.2: "Cards can later be enumerated and narrowed by `property_id`, by
    `status`, or by `superseded_by_rate_card_id` to find every card that a given
    card displaced."

    Design: Corner/entities/superseded_rate_card_is_reachable_by_self_reference_filter
    """
    prop = create_property()
    card_a = create_rate_card(prop["id"], label="2026 Season Card A")
    add_rate_card_line(
        card_a["id"], asset_class="DIGITAL_BOARD", base_unit_price_cents=250_000
    )
    publish_rate_card(card_a["id"])

    card_b = create_rate_card(prop["id"], label="2026 Season Card B")
    add_rate_card_line(
        card_b["id"], asset_class="DIGITAL_BOARD", base_unit_price_cents=260_000
    )

    published_b = validate_success(api.publish_rate_card(card_b["id"], ADMIN))
    assert_rate_card(published_b)
    assert published_b["status"] == "PUBLISHED"

    reread_a = validate_success(api.get_rate_card(card_a["id"], ADMIN))
    assert reread_a["status"] == "SUPERSEDED"
    assert reread_a["superseded_by_rate_card_id"] == card_b["id"], (
        "the displaced card points at the card that displaced it"
    )

    rows, meta = validate_paginated(
        api.list_rate_cards(ADMIN, {"superseded_by_rate_card_id": card_b["id"]})
    )
    assert len(rows) == 1, f"expected exactly 1 superseded card, got {len(rows)}"
    assert rows[0]["id"] == card_a["id"]
    assert meta["total_count"] == 1


def test_publishing_an_already_published_card_is_rejected(api):
    """PRD §3.2: "The owning property must be in `PLANNING`, `SELLING` or
    `IN_SEASON` — publishing against a `CLOSED` property is rejected with
    `ERR_INVALID_STATE` — and so is publishing a card that has already left
    `DRAFT`, whether it now sits in `PUBLISHED` or in `SUPERSEDED`."
    PRD §3.2: "A `PropertyAdmin` opens one against a property by giving it a
    `label` of 1 to 80 characters and an `effective_year` between 2020 and 2100
    inclusive; the card is born in `DRAFT` with `line_count` at 0, `published_at`
    null and `superseded_by_rate_card_id` null, and its `property_id` is taken
    from the position of the property in the request path."

    Design: Corner/state_machines/rate_card_publish_twice_returns_invalid_state
    """
    prop = create_property()
    card = create_rate_card(prop["id"])
    add_rate_card_line(
        card["id"], asset_class="DIGITAL_BOARD", base_unit_price_cents=250_000
    )
    first = publish_rate_card(card["id"])
    first_published_at = first["published_at"]

    response = api.publish_rate_card(card["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    assert response.status_code == 409

    reread = validate_success(api.get_rate_card(card["id"], ADMIN))
    assert reread["status"] == "PUBLISHED"
    assert reread["published_at"] == first_published_at, (
        "the rejected republication must not restamp published_at"
    )
    assert reread["superseded_by_rate_card_id"] is None


def test_rate_card_lines_are_scoped_to_their_own_card(api):
    """PRD §3.2: "Adding a line raises the owning card's `line_count` by 1 and
    increments that card's `version` by 1; the line itself is written once and
    carries neither `updated_at` nor `version`, and it records its owning
    `rate_card_id` from the request path."
    PRD §3.2: "A **RateCardLine** prices exactly one inventory class and is added
    only while the owning card is still `DRAFT` — adding a line to a `PUBLISHED`
    or `SUPERSEDED` card is rejected with `ERR_INVALID_STATE`."

    Design: Corner/endpoints/rate_card_lines_subresource_is_scoped_to_its_card
    """
    prop = create_property()
    card_a = create_rate_card(prop["id"], label="Card A")
    add_rate_card_line(
        card_a["id"], asset_class="DIGITAL_BOARD", base_unit_price_cents=250_000
    )
    add_rate_card_line(
        card_a["id"], asset_class="SIGNAGE", base_unit_price_cents=100_000
    )
    card_b = create_rate_card(prop["id"], label="Card B", effective_year=2027)
    add_rate_card_line(
        card_b["id"], asset_class="HOSPITALITY", base_unit_price_cents=900_000
    )

    lines_a = validate_success(api.list_rate_card_lines(card_a["id"], ADMIN))
    lines_b = validate_success(api.list_rate_card_lines(card_b["id"], ADMIN))

    assert len(lines_a) == 2, f"card A prices 2 classes, got {len(lines_a)}"
    assert len(lines_b) == 1, f"card B prices 1 class, got {len(lines_b)}"
    assert lines_b[0]["asset_class"] == "HOSPITALITY"

    for line in lines_a:
        assert_rate_card_line(line)
        assert line["rate_card_id"] == card_a["id"]
    for line in lines_b:
        assert_rate_card_line(line)
        assert line["rate_card_id"] == card_b["id"]

    assert validate_success(api.get_rate_card(card_a["id"], ADMIN))["line_count"] == 2
    assert validate_success(api.get_rate_card(card_b["id"], ADMIN))["line_count"] == 1


def test_duplicate_clause_ref_and_duplicate_rate_line_are_rejected(api):
    """PRD §3.4: "The clause reference must be unique within its contract; a
    repeat is rejected with `ERR_DUPLICATE_CLAUSE_REF`."
    PRD §3.2: "A card may hold at most one line per class; a second line for a
    class the card already prices is rejected with `ERR_DUPLICATE_RATE_LINE`."

    Design: Corner/validations/uniqueness_violations_on_clause_ref_and_rate_line
    """
    prop = create_property()
    card = create_rate_card(prop["id"])
    add_rate_card_line(
        card["id"], asset_class="DIGITAL_BOARD", base_unit_price_cents=250_000
    )
    asset = create_inventory_asset(
        prop["id"], name="North LED Ribbon", asset_class="DIGITAL_BOARD",
        capacity_units=6, changeover_buffer_minutes=0,
    )
    sponsor = create_sponsor()
    contract = create_contract(sponsor["id"], prop["id"])
    add_entitlement(
        contract["id"], asset["id"], clause_ref="4.2(a)", promised_units=10
    )

    duplicate_clause = api.create_entitlement(
        contract["id"],
        {
            "inventory_asset_id": asset["id"],
            "clause_ref": "4.2(a)",
            "promised_units": 4,
        },
        SELLER,
    )
    validate_error(duplicate_clause, ApiErrorId.ERR_DUPLICATE_CLAUSE_REF.value)

    duplicate_line = api.create_rate_card_line(
        card["id"],
        {"asset_class": "DIGITAL_BOARD", "base_unit_price_cents": 300_000},
        ADMIN,
    )
    validate_error(duplicate_line, ApiErrorId.ERR_DUPLICATE_RATE_LINE.value)

    assert validate_success(api.get_rate_card(card["id"], ADMIN))["line_count"] == 1

    rows, meta = validate_paginated(
        api.list_entitlements(SELLER, {"contract_id": contract["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the duplicate clause must not persist, got {meta['total_count']} rows"
    )
    assert rows[0]["clause_ref"] == "4.2(a)"
