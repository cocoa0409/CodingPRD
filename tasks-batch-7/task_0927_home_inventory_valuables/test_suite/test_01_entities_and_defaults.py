"""Entity-level claims: declared defaults, not-found routing, the pagination
envelope, required fields and the light projection of a package line."""
from test_helpers import (
    ApiErrorId,
    add_cataloged_item,
    add_generated_package,
    add_policy,
    add_room,
    assert_item,
    assert_package_line,
    assert_same_instant,
    assert_three_digit_utc,
    bootstrap_household,
    create_item_payload,
    create_member_payload,
    make_anonymous_headers,
    make_homeowner_headers,
    register_owner,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

GENERAL_SCHEDULE = {
    "category": "GENERAL",
    "useful_life_months": 120,
    "annual_depreciation_pct": 8.0,
    "salvage_floor_pct": 20.0,
    "blanket_sublimit_cents": 900000,
    "appraisal_scope": "GENERAL",
    "serial_required": False,
}


def test_item_creation_applies_the_declared_defaults(api):
    """PRD 3.3: "A new item lands in `lifecycle_state` `DRAFT` with `evidence_tier`
    `NONE`, `valuation_state` `UNVALUED`, `effective_value_cents` 0,
    `effective_value_basis` `NONE`, `coverage_mode` `BLANKET`, `scheduled_policy_id`
    null, `scheduled_value_cents` 0, `declared_value_cents` 0,
    `declared_by_member_id` null, `replaces_item_id` null, `serial_chain_intact`
    true, `allocated_quantity` 0 and `frozen_by_claim_id` null; its
    `acv_value_cents` is computed immediately against the current clock."
    PRD 3.3: "`quantity` defaults to 1 and must be between 1 and 999 inclusive."
    PRD 2.5: "A row created before any clock advance therefore carries `created_at`
    of `2026-05-01T00:00:00.000Z`."

    Design: Corner/entities/create_item_applies_declared_defaults_and_initial_derived_state
    """
    ctx = bootstrap_household(
        tier="PLUS", activate=False, clock=None, categories=[GENERAL_SCHEDULE]
    )
    room = add_room(ctx, name="Hall", floor_label="1")

    response = api.create_item(
        create_item_payload(
            ctx["household_id"],
            room["id"],
            name="Plain Chair",
            category="GENERAL",
            acquired_at="2025-01-01T00:00:00Z",
        ),
        ctx["owner_headers"],
    )
    item = validate_success(response, 201)
    assert_item(item)

    assert item["quantity"] == 1
    assert item["lifecycle_state"] == "DRAFT"
    assert item["evidence_tier"] == "NONE"
    assert item["valuation_state"] == "UNVALUED"
    assert item["effective_value_basis"] == "NONE"
    assert item["effective_value_cents"] == 0
    assert item["coverage_mode"] == "BLANKET"
    assert item["version"] == 1
    assert_three_digit_utc(item["created_at"], "Item.created_at")
    assert_same_instant(item["created_at"], "2026-05-01T00:00:00Z", "Item.created_at")


def test_unknown_item_id_in_the_path_returns_the_item_not_found_error(api):
    """PRD 2.8 rung 5: "an unresolvable item id produces `ERR_ITEM_NOT_FOUND`; every
    other unresolvable path resource — member, room, subscription, policy, package,
    package line, appraiser, appraisal, claim, claim line, estate plan, allocation,
    share grant, asset — produces `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/entities/get_item_with_unknown_id_returns_item_not_found
    """
    owner = register_owner()
    owner_headers = make_homeowner_headers(owner["id"])
    validate_success(
        api.create_household(
            {"name": "Corner House 2", "address_label": "2 Corner St"}, owner_headers
        ),
        201,
    )

    response = api.get_item("00000000-0000-4000-8000-000000000000", owner_headers)
    validate_error(response, ApiErrorId.ERR_ITEM_NOT_FOUND.value, 404)
    assert response.json()["response_type"] == "error"


def test_item_list_reports_the_pagination_envelope(api):
    """PRD 2.3: "Every list endpoint accepts `limit` and `offset`. `limit` defaults
    to 10, has a minimum of 1 and a maximum of 100; `offset` defaults to 0 and has a
    minimum of 0. Both are reported back in `meta` together with `total_count` (the
    number of rows matching the filters before the page window is applied) and
    `has_more` (true when rows remain after the current window)."

    Design: Corner/entities/list_items_returns_pagination_envelope_fields
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, categories=[GENERAL_SCHEDULE])
    room = add_room(ctx, name="Store", floor_label="0")
    for index, acquired in enumerate(
        ("2025-01-01T00:00:00Z", "2025-01-02T00:00:00Z", "2025-01-03T00:00:00Z"), start=1
    ):
        validate_success(
            api.create_item(
                create_item_payload(
                    ctx["household_id"],
                    room["id"],
                    name=f"P{index}",
                    category="GENERAL",
                    acquired_at=acquired,
                ),
                ctx["owner_headers"],
            ),
            201,
        )

    first_rows, first_meta = validate_paginated(
        api.list_items(
            ctx["owner_headers"],
            params={"household_id": ctx["household_id"], "limit": 2, "offset": 0},
        )
    )
    assert len(first_rows) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True

    second_rows, second_meta = validate_paginated(
        api.list_items(
            ctx["owner_headers"],
            params={"household_id": ctx["household_id"], "limit": 2, "offset": 2},
        )
    )
    assert len(second_rows) == 1
    assert second_meta["has_more"] is False


def test_item_creation_without_the_required_acquisition_instant_is_rejected(api):
    """PRD 2.8 rung 3: "**`ERR_INVALID_REQUEST` (400)** — a required body field is
    missing, a JSON type does not match, a required array is empty, or a datetime
    field does not parse as ISO 8601 UTC."
    PRD 3.3: "An item is created with a `household_id`, a `room_id` naming a room of
    that same household, a `name`, a `category`, an `acquired_at` instant, and
    optionally a `quantity`, a `serial_number`, a `purchase_price_cents` and a
    `replacement_cost_cents`."

    Design: Corner/entities/create_item_missing_required_field_returns_invalid_request
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, categories=[GENERAL_SCHEDULE])
    room = add_room(ctx, name="Pantry", floor_label="0")

    response = api.create_item(
        {
            "household_id": ctx["household_id"],
            "room_id": room["id"],
            "name": "No Date Item",
            "category": "GENERAL",
        },
        ctx["owner_headers"],
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    rows, meta = validate_paginated(
        api.list_items(ctx["owner_headers"], params={"household_id": ctx["household_id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_package_line_carries_no_version_and_no_updated_at(api):
    """PRD 2.4: "`Asset`, `CategorySchedule` and `PackageLine` carry only `id` and
    `created_at`: they have **no** `updated_at` field and **no** `version` field,
    and nothing in this document may be read as bumping a version on them."
    PRD 2.11: "**`PackageLine`**: `id`, `created_at`, `package_id`, `item_id`,
    `snapshot_name`, `snapshot_category`, `snapshot_evidence_tier`,
    `snapshot_effective_value_cents`, `snapshot_effective_value_basis`,
    `snapshot_covered_cents`, `snapshot_coverage_mode`, `stale`. No `updated_at`, no
    `version`."
    PRD 3.6: "The remaining snapshot fields copy the item verbatim at that instant:
    `snapshot_name` from `name`, `snapshot_category` from `category`,
    `snapshot_evidence_tier` from `evidence_tier`, `snapshot_effective_value_basis`
    from `effective_value_basis` and `snapshot_coverage_mode` from `coverage_mode`.
    Every line starts with `stale` false."

    Design: Corner/entities/package_line_is_immutable_and_exposes_no_version_field
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, categories=[GENERAL_SCHEDULE])
    room = add_room(ctx, name="Study", floor_label="1")
    add_cataloged_item(
        ctx, room["id"], 150000, name="Desk", acquired_at="2025-01-01T00:00:00Z"
    )
    policy = add_policy(ctx, policy_number="NW-C6")
    package = add_generated_package(ctx, policy["id"])

    rows, meta = validate_paginated(
        api.list_package_lines(ctx["owner_headers"], params={"package_id": package["id"]})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1

    line = rows[0]
    assert_package_line(line)
    assert "version" not in line
    assert "updated_at" not in line
    assert line["snapshot_effective_value_cents"] == 150000
    assert line["snapshot_effective_value_basis"] == "DECLARED"
    assert line["snapshot_evidence_tier"] == "PHOTO_ONLY"
    assert line["stale"] is False


def test_self_registration_yields_an_owner_with_no_household(api):
    """PRD 3.1: "Omitting `household_id` self-registers an unattached person, and in
    that case `member_role` is set to `OWNER`; supplying `household_id` attaches the
    person to an existing household, and in that case `member_role` falls back to
    `LIMITED`."
    PRD 3.1: "Creating the household writes the new household's id onto the acting
    member's `household_id` and forces that member's `member_role` to `OWNER`, and
    the household's `write_gate_state` initialises to `OPEN`."

    Design: Corner/entities/member_self_registration_defaults_to_owner_and_null_household
    """
    set_clock("2026-05-01T00:00:00Z")

    member = validate_success(
        api.create_member(
            create_member_payload(email="c7@example.com", full_name="Corner Seven"),
            make_anonymous_headers(),
        ),
        201,
    )
    assert member["member_role"] == "OWNER"
    assert member["household_id"] is None

    owner_headers = make_homeowner_headers(member["id"])
    household = validate_success(
        api.create_household(
            {"name": "Corner House 7", "address_label": "7 Corner St"}, owner_headers
        ),
        201,
    )
    assert household["write_gate_state"] == "OPEN"
    assert household["item_count"] == 0

    bound = validate_success(api.get_member(member["id"], owner_headers))
    assert bound["household_id"] == household["id"]

    rows, meta = validate_paginated(
        api.list_members(owner_headers, params={"household_id": household["id"]})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_a_second_registration_with_the_same_email_is_rejected(api):
    """PRD 3.1: "A person enters the platform as a **Member**, identified by an
    `email` that must be unique across the whole platform — a second registration
    with an email that already exists is rejected with `ERR_INVALID_REQUEST` — and a
    `full_name`."

    Design: Corner/entities/duplicate_member_email_is_rejected
    """
    validate_success(
        api.create_member(
            create_member_payload(email="c8@example.com", full_name="Corner Eight"),
            make_anonymous_headers(),
        ),
        201,
    )

    response = api.create_member(
        create_member_payload(email="c8@example.com", full_name="Corner Eight Again"),
        make_anonymous_headers(),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_unknown_household_id_in_the_path_returns_the_household_not_found_error(api):
    """PRD 2.8 rung 5: "**`ERR_HOUSEHOLD_NOT_FOUND` (404)** — an id in the request
    **path** does not resolve. Path ids are validated left to right, so the leftmost
    unresolvable segment decides the error. An unresolvable household id produces
    `ERR_HOUSEHOLD_NOT_FOUND`"

    Design: Corner/entities/get_household_with_unknown_id_returns_household_not_found
    """
    owner = register_owner(email="c9@example.com", full_name="Corner Nine")
    owner_headers = make_homeowner_headers(owner["id"])

    response = api.get_household("11111111-1111-4111-8111-111111111111", owner_headers)
    validate_error(response, ApiErrorId.ERR_HOUSEHOLD_NOT_FOUND.value, 404)


def test_unresolvable_body_room_id_returns_the_reference_not_found_error(api):
    """PRD 2.8 rung 6: "**`ERR_REFERENCE_NOT_FOUND` (404)** — a foreign key supplied
    in the request **body** does not resolve: `household_id`, `room_id`, `item_id`,
    `policy_id`, `package_id`, `appraiser_id`, `heir_member_id`,
    `executor_member_id`, `scope_room_id`, `scope_package_id`, `scope_claim_id`, or
    any element of `affected_room_ids`."

    Design: Corner/entities/body_foreign_key_to_missing_room_returns_reference_not_found
    """
    ctx = bootstrap_household(tier="PLUS", activate=False, clock=None, categories=[GENERAL_SCHEDULE])

    response = api.create_item(
        {
            "household_id": ctx["household_id"],
            "room_id": "22222222-2222-4222-8222-222222222222",
            "name": "Orphan",
            "category": "GENERAL",
            "acquired_at": "2025-01-01T00:00:00Z",
        },
        ctx["owner_headers"],
    )
    validate_error(response, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value, 404)

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["item_count"] == 0
