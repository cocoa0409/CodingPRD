"""Catalog, delivery network and membership: registration, dues, tier changes
and the immutable price history."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_credit_grant,
    assert_item,
    assert_member,
    assert_price_version,
    assert_route,
    assert_same_instant,
    build_catalog,
    create_credit_grant_payload,
    create_drop_point_payload,
    create_item_payload,
    create_member_payload,
    create_price_version_payload,
    create_route_payload,
    dues_payment_payload,
    get_success_data,
    is_valid_uuid,
    make_member_headers,
    member_version,
    open_cycle,
    open_drop_run,
    publish_item,
    set_clock,
    shift_iso,
    tier_change_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["club_admin_headers"]


# ---------------------------------------------------------------- routes ---
def test_create_route_returns_every_declared_field(api):
    """PRD §3.2: "A route models a truck run. It carries a unique non-empty
    `code`, a human-readable `name`, a `reefer_slots` count of refrigerated
    pallet positions which defaults to 2 and may not be negative, a
    `route_minimum_cents` which defaults to 250000 and may not be negative,
    and a `max_pallets` total of pallet positions across all temperature
    classes which defaults to 12 and must be at least 1."
    PRD §3.2: "From `reefer_slots` the server derives `cold_capable`, which is
    true exactly when `reefer_slots` is greater than 0; a route that is not
    cold-capable may not carry frozen or chilled goods at all."
    PRD §2.4: "All resources except one additionally carry `updated_at`, in the
    same timestamp format, and `version`, an integer that starts at 1 when the
    row is created and is incremented by exactly 1 on every mutation of that
    row."

    Design: Corner/entities/create_route_returns_every_declared_field
    """
    set_clock(api, "2026-05-05T00:00:00Z")
    payload = create_route_payload(route_minimum_cents=250000)
    route = validate_success(api.create_route(payload, ADMIN), 201)

    assert_route(route)
    assert route["code"] == "R-NORTH"
    assert route["reefer_slots"] == 2
    assert route["route_minimum_cents"] == 250000
    assert route["max_pallets"] == 12
    assert route["cold_capable"] is True
    assert route["version"] == 1
    assert is_valid_uuid(route["id"]), "id must be a UUID with no type prefix"


def test_create_route_applies_declared_defaults_when_optionals_are_omitted(api):
    """PRD §3.2: "A route models a truck run. It carries a unique non-empty
    `code`, a human-readable `name`, a `reefer_slots` count of refrigerated
    pallet positions which defaults to 2 and may not be negative, a
    `route_minimum_cents` which defaults to 250000 and may not be negative,
    and a `max_pallets` total of pallet positions across all temperature
    classes which defaults to 12 and must be at least 1."

    Design: Corner/entities/create_route_applies_declared_defaults_when_optionals_are_omitted
    """
    set_clock(api, "2026-05-05T00:00:00Z")
    route = validate_success(
        api.create_route({"code": "R-DEFAULTS", "name": "Defaults Route"}, ADMIN), 201
    )

    assert route["reefer_slots"] == 2
    assert route["route_minimum_cents"] == 250000
    assert route["max_pallets"] == 12
    assert route["cold_capable"] is True


# ------------------------------------------------------------ membership ---
def test_member_tier_rank_and_discount_pct_are_derived_from_tier(api):
    """PRD §3.1: "The three tiers are `BASIC`, `PLUS` and `PRO`, and each
    carries two derived attributes that the server writes rather than accepts:
    `tier_rank`, which is 1 for `BASIC`, 2 for `PLUS` and 3 for `PRO`, and
    `discount_pct`, which is 0.00 for `BASIC`, 0.05 for `PLUS` and 0.09 for
    `PRO`."
    PRD §3.1: "A newly registered member has status `PENDING`, a
    `lifetime_dues_paid_cents` of 0, a `credit_balance_cents` of 0, an
    `is_coordinator` flag of false, and a null `dues_paid_through` and
    `dues_grace_until`."

    Design: Corner/entities/member_tier_rank_and_discount_pct_are_derived_from_tier
    """
    set_clock(api, "2026-05-05T00:00:00Z")
    route = get_success_data(
        api.create_route({"code": "R-NORTH", "name": "North Route"}, ADMIN)
    )
    depot = get_success_data(
        api.create_drop_point({"route_id": route["id"], "name": "Depot A"}, ADMIN)
    )

    member = validate_success(
        api.create_member(
            create_member_payload(
                depot["id"],
                email="new@coop.test",
                full_name="New Member",
                tier="PLUS",
            ),
            ADMIN,
        ),
        201,
    )

    assert_member(member)
    assert member["tier"] == "PLUS"
    assert member["tier_rank"] == 2
    assert member["discount_pct"] == 0.05
    assert member["status"] == "PENDING"
    assert member["credit_balance_cents"] == 0
    assert member["dues_paid_through"] is None
    assert member["is_coordinator"] is False


def test_naming_a_coordinator_sets_is_coordinator_on_that_member(api):
    """PRD §3.2: "Naming a coordinator has a side effect on the member record:
    that member's `is_coordinator` becomes true."
    PRD §3.1: "The `is_coordinator` flag is derived, not set by hand: it is true
    exactly when at least one drop point names this member as its
    `coordinator_member_id`."

    Design: Corner/entities/naming_a_coordinator_sets_is_coordinator_on_that_member
    """
    w = build_catalog(api, items=())

    cora = validate_success(api.get_member(w.cora_id, ADMIN))
    assert cora["is_coordinator"] is True
    assert cora["tier_rank"] == 3
    assert cora["status"] == "ACTIVE"

    rows, meta = validate_paginated(
        api.list_drop_points(ADMIN, params={"coordinator_member_id": w.cora_id})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == w.depot_b_id


# ----------------------------------------------------------------- items ---
def test_item_defaults_are_applied_and_status_starts_active(api):
    """PRD §3.2: "An item carries a unique non-empty `sku`, a display `name`, a
    `temp_class` of `FROZEN`, `CHILLED` or `DRY`, a `case_pack_units` count of
    at least 1 giving how many member-facing units the supplier packs into one
    case, a `unit_weight_grams` of at least 1, a `unit_cube_cm3` of at least 1,
    a `split_allowed` flag defaulting to true, and a `remainder_policy`
    defaulting to `SHORT_FILL`."
    PRD §3.2: "An item's `status` starts at `ACTIVE`; retiring an item moves it
    `ACTIVE → DISCONTINUED`, which is terminal."

    Design: Corner/entities/system_fields_supplied_by_the_caller_are_ignored
    """
    set_clock(api, "2026-05-05T00:00:00Z")
    item = validate_success(
        api.create_item(
            {
                "sku": "OAT-25",
                "name": "Rolled Oats 25lb",
                "temp_class": "DRY",
                "case_pack_units": 4,
                "unit_weight_grams": 1000,
                "unit_cube_cm3": 3000,
            },
            ADMIN,
        ),
        201,
    )

    assert_item(item)
    assert item["status"] == "ACTIVE"
    assert item["split_allowed"] is True
    assert item["remainder_policy"] == "SHORT_FILL"
    assert item["version"] == 1


def test_create_item_missing_temp_class_returns_validation_error(api):
    """PRD §2.9: "**Rung 7** — every field the endpoint declares as required is
    present and of the declared type. Applies to every endpoint. Failure:
    `ERR_VALIDATION`, HTTP 400."

    Design: Corner/entities/create_item_missing_temp_class_returns_validation_error
    """
    set_clock(api, "2026-05-05T00:00:00Z")
    response = api.create_item(
        {
            "sku": "NO-TEMP",
            "name": "Missing Temp Class",
            "case_pack_units": 4,
            "unit_weight_grams": 1000,
            "unit_cube_cm3": 3000,
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value)

    _, meta = validate_paginated(api.list_items(ADMIN))
    assert meta["total_count"] == 0, "the rejected item must not have been stored"


def test_create_item_with_an_unknown_temp_class_returns_invalid_enum(api):
    """PRD §2.9: "**Rung 8** — every enum-typed field carries a value from that
    field's declared member list. This covers `tier`, `new_tier`, `temp_class`,
    `remainder_policy`, `substitution_pref`, `payout_mode`, `destination`,
    `simulated_outcome`, and every enum-valued filter on a list endpoint
    including `status`, `payment_status`, `kind` and `source`. Applies to every
    endpoint. Failure: `ERR_INVALID_ENUM`, HTTP 400."

    Design: Corner/entities/create_item_with_an_unknown_temp_class_returns_invalid_enum
    """
    set_clock(api, "2026-05-05T00:00:00Z")
    response = api.create_item(
        {
            "sku": "BAD-TEMP",
            "name": "Bad Temp Class",
            "temp_class": "AMBIENT",
            "case_pack_units": 4,
            "unit_weight_grams": 1000,
            "unit_cube_cm3": 3000,
        },
        ADMIN,
    )
    body = validate_error(response, ApiErrorId.ERR_INVALID_ENUM.value)
    assert body["error_id"] != ApiErrorId.ERR_VALIDATION.value


# ------------------------------------------------------- reference lookup --
def test_get_drop_run_with_an_unknown_id_returns_drop_run_not_found(api):
    """PRD §2.8: "Identifiers embedded in a URL path are resolved left to right,
    and the first one that resolves to nothing terminates the request."
    PRD §2.8: "`drop_run_id` yields `ERR_DROP_RUN_NOT_FOUND`"

    Design: Corner/entities/get_drop_run_with_an_unknown_id_returns_drop_run_not_found
    """
    w = build_catalog(api, items=())
    open_cycle(api, w)
    open_drop_run(api, w)

    validate_error(
        api.get_drop_run(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_DROP_RUN_NOT_FOUND.value,
    )


def test_create_drop_point_with_an_unknown_route_returns_route_not_found(api):
    """PRD §2.8: "`route_id` yields `ERR_ROUTE_NOT_FOUND`"
    PRD §2.9: "**Rung 5** — every foreign key supplied in the request body
    resolves to a stored row, checked in the order the fields appear in the
    endpoint's input list, using the mapping of §2.8."

    Design: Corner/entities/create_drop_point_with_an_unknown_route_returns_route_not_found
    """
    set_clock(api, "2026-05-05T00:00:00Z")
    validate_error(
        api.create_drop_point(
            {"route_id": NON_EXISTENT_UUID, "name": "Orphan Depot"}, ADMIN
        ),
        ApiErrorId.ERR_ROUTE_NOT_FOUND.value,
    )

    _, meta = validate_paginated(api.list_drop_points(ADMIN))
    assert meta["total_count"] == 0


def test_create_member_with_an_unknown_home_drop_point_returns_drop_point_not_found(api):
    """PRD §2.8: "`home_drop_point_id` and `drop_point_id` yield
    `ERR_DROP_POINT_NOT_FOUND`"

    Design: Corner/entities/create_member_with_an_unknown_home_drop_point_returns_drop_point_not_found
    """
    set_clock(api, "2026-05-05T00:00:00Z")
    get_success_data(
        api.create_route({"code": "R-NORTH", "name": "North Route"}, ADMIN)
    )
    validate_error(
        api.create_member(
            {
                "email": "orphan@coop.test",
                "full_name": "Orphan Member",
                "home_drop_point_id": NON_EXISTENT_UUID,
            },
            ADMIN,
        ),
        ApiErrorId.ERR_DROP_POINT_NOT_FOUND.value,
    )


# --------------------------------------------------------- price versions --
def test_price_version_is_immutable_and_exposes_no_version_field(api):
    """PRD §2.4: "The single exception is the price version. A published price
    is immutable and append-only: a `PriceVersion` row carries `id` and
    `created_at` and nothing else of the common set — it has no `updated_at`
    and no `version` field at all, and no endpoint mutates one once written."
    PRD §3.2: "Publishing a price supplies the `item_id`, an `effective_from`
    instant and a `case_price_cents` of at least 1, and the server additionally
    derives `split_unit_base_cents` as the ceiling of `case_price_cents` divided
    by the item's `case_pack_units` — the per-unit price before any split-case
    fee, rounded **up** to the whole cent rather than to nearest."

    Design: Corner/entities/price_version_is_immutable_and_exposes_no_version_field
    """
    w = build_catalog(api, items=("oat",), oat_late_price=False)
    price_version_id = w.prices["oat"][0]

    price = validate_success(api.get_price_version(price_version_id, ADMIN))
    assert_price_version(price)
    assert price["case_price_cents"] == 12000
    assert price["split_unit_base_cents"] == 3000
    assert "updated_at" not in price
    assert "version" not in price


def test_listing_items_returns_pagination_counters_and_honours_limit(api):
    """PRD §2.3: "List responses populate `limit`, `offset`, `total_count` and
    `has_more` in `meta`; `total_count` counts the rows matching the filters
    before pagination is applied, and `has_more` is true when rows remain beyond
    the current page."

    Design: Corner/entities/listing_items_returns_pagination_counters_and_honours_limit
    """
    build_catalog(api, items=("oat", "berry", "cheese", "rice"))

    rows, meta = validate_paginated(api.list_items(ADMIN, params={"limit": 2, "offset": 0}))
    assert len(rows) == 2
    assert meta["total_count"] == 4
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0


def test_filtered_list_by_foreign_key_returns_only_the_matching_children(api):
    """PRD §3.2: "Price versions may be listed filtered by `item_id`, and each
    one is individually readable."
    PRD §2.3: "Filters offered by a collection endpoint are combined
    conjunctively, and any enum-typed filter value outside that field's declared
    member list is rejected with `ERR_INVALID_ENUM` (HTTP 400)."

    Design: Corner/entities/filtered_list_by_foreign_key_returns_only_the_matching_children
    """
    w = build_catalog(api, items=("oat", "cheese"))

    oat_rows, oat_meta = validate_paginated(
        api.list_price_versions(ADMIN, params={"item_id": w.items["oat"]})
    )
    assert oat_meta["total_count"] == 2
    assert all(row["item_id"] == w.items["oat"] for row in oat_rows)

    cheese_rows, cheese_meta = validate_paginated(
        api.list_price_versions(ADMIN, params={"item_id": w.items["cheese"]})
    )
    assert cheese_meta["total_count"] == 1
    assert cheese_rows[0]["case_price_cents"] == 10000
    assert cheese_rows[0]["split_unit_base_cents"] == 3334


def test_duplicate_effective_from_for_one_item_is_refused(api):
    """PRD §3.2: "Two rows for the same item may not share an `effective_from`
    instant, because an item's price history is read as a partition of half-open
    intervals and a shared left endpoint would make the partition ambiguous; the
    duplicate is refused with `ERR_PRICE_VERSION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/price_version_point_collision_rejects_a_duplicate_effective_from
    """
    w = build_catalog(api, items=("oat",), oat_late_price=False)

    validate_error(
        api.create_price_version(
            create_price_version_payload(
                w.items["oat"], 12500, effective_from="2026-04-01T00:00:00Z"
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_PRICE_VERSION_OVERLAP.value,
    )


def test_a_price_one_second_later_needs_no_buffer_and_is_admitted(api):
    """PRD §3.2: "A price version, once written, is never mutated; a price change
    is a new row with a later `effective_from`."
    PRD §3.2: "Publishing a price supplies the `item_id`, an `effective_from`
    instant and a `case_price_cents` of at least 1, and the server additionally
    derives `split_unit_base_cents` as the ceiling of `case_price_cents` divided
    by the item's `case_pack_units` — the per-unit price before any split-case
    fee, rounded **up** to the whole cent rather than to nearest."

    Design: Difficulty/resource_temporal_overlap/price_version_point_collision_rejects_a_duplicate_effective_from
    """
    w = build_catalog(api, items=("oat",), oat_late_price=False)

    adjacent = validate_success(
        api.create_price_version(
            create_price_version_payload(
                w.items["oat"], 12500, effective_from="2026-04-01T00:00:01Z"
            ),
            ADMIN,
        ),
        201,
    )
    assert adjacent["case_price_cents"] == 12500
    assert adjacent["split_unit_base_cents"] == 3125

    _, meta = validate_paginated(
        api.list_price_versions(ADMIN, params={"item_id": w.items["oat"]})
    )
    assert meta["total_count"] == 2


# --------------------------------------------------------- dues and tiers --
def test_tier_upgrade_proration_counts_the_change_day_by_ceiling(api):
    """PRD §3.1: "Otherwise the remaining-days count is the **ceiling** of the
    number of days between the clock and `dues_paid_through`, so a member 200.4
    days from expiry counts as 201 remaining days and the day on which the change
    is made counts as remaining."
    PRD §3.1: "Otherwise the prorated amount is the difference between the two
    annual dues figures, multiplied by the remaining-days count, divided by 365,
    and rounded half up to the whole cent."
    PRD §3.1: "On acceptance the server rewrites `tier`, `tier_rank` and
    `discount_pct` to the new tier's values and adds `prorated_amount_cents` to
    `lifetime_dues_paid_cents`."

    Design: Difficulty/dual_variant_calc/tier_upgrade_proration_counts_the_change_day_by_ceiling
    """
    w = build_catalog(api, items=())
    set_clock(api, "2026-05-10T06:00:00Z")

    version = member_version(api, w, w.mara_id)
    member = validate_success(
        api.change_tier(
            w.mara_id,
            tier_change_payload("PRO", 8877, version),
            make_member_headers(w.mara_id),
        )
    )

    assert member["tier"] == "PRO"
    assert member["tier_rank"] == 3
    assert member["discount_pct"] == 0.09
    assert member["lifetime_dues_paid_cents"] == 17877
    assert_same_instant(
        member["dues_paid_through"], "2027-05-05T00:00:00Z", "dues_paid_through"
    )


def test_tier_upgrade_prorated_amount_below_the_ceiling_figure_is_refused(api):
    """PRD §3.1: "The request is accepted only when `prorated_amount_cents`
    matches that figure exactly; otherwise it fails with `ERR_VALIDATION`."
    PRD §2.9: "**Rung 55** — for a dues payment, `amount_cents` equals the annual
    dues of the member's tier multiplied by `term_years`; for a tier change,
    `prorated_amount_cents` equals the figure the proration rule produces."

    Design: Difficulty/dual_variant_calc/tier_upgrade_proration_counts_the_change_day_by_ceiling
    """
    w = build_catalog(api, items=())
    set_clock(api, "2026-05-10T06:00:00Z")

    version = member_version(api, w, w.mara_id)
    validate_error(
        api.change_tier(
            w.mara_id,
            tier_change_payload("PRO", 8852, version),
            make_member_headers(w.mara_id),
        ),
        ApiErrorId.ERR_VALIDATION.value,
    )

    member = validate_success(api.get_member(w.mara_id, ADMIN))
    assert member["tier"] == "PLUS", "the rejected change must not have moved the tier"


def test_membership_lapses_after_grace_and_reinstates_from_the_clock(api):
    """PRD §3.1: "Lapsing is an explicit administrative act, not an automatic
    one, and it is only available once the grace period has genuinely expired: a
    member may be moved `ACTIVE → LAPSED` only when `dues_grace_until` is not null
    and the clock is strictly after it."
    PRD §3.1: "A member who had fallen to `LAPSED` and now pays moves
    `LAPSED → ACTIVE` — this is the reinstatement leg, and the new
    `dues_paid_through` is measured from the current clock reading, not from the
    stale `dues_paid_through` the member was carrying, so a member who lapsed a
    year ago and reinstates today gets a full term from today and no back-credit
    for the gap."

    Design: Difficulty/non_linear_state_machine/membership_status_cycles_active_to_lapsed_and_back_to_active
    """
    w = build_catalog(api, items=())
    set_clock(api, "2027-05-20T00:00:00Z")

    lapsed = validate_success(api.lapse_member(w.mara_id, ADMIN))
    assert lapsed["status"] == "LAPSED"

    reinstated = validate_success(
        api.pay_dues(
            w.mara_id, dues_payment_payload(9000, lapsed["version"]), ADMIN
        )
    )
    assert reinstated["status"] == "ACTIVE"
    assert_same_instant(
        reinstated["dues_paid_through"], "2028-05-19T00:00:00Z", "dues_paid_through"
    )
    assert_same_instant(
        reinstated["dues_grace_until"], "2028-06-02T00:00:00Z", "dues_grace_until"
    )
    assert reinstated["lifetime_dues_paid_cents"] == 18000


def test_dues_payment_sets_paid_through_and_grace_and_activates_the_member(api):
    """PRD §3.1: "On acceptance the server sets `dues_paid_through` to the
    current clock reading plus 365 days multiplied by `term_years`, sets
    `dues_grace_until` to `dues_paid_through` plus a further 14 days, adds
    `amount_cents` to `lifetime_dues_paid_cents`, runs the credit expiry sweep
    for this member, and moves the membership status to `ACTIVE`."
    PRD §3.1: "The annual dues are 3000 cents at `BASIC`, 9000 cents at `PLUS`
    and 18000 cents at `PRO`; a two-year `PRO` payment is therefore exactly
    36000 cents, and anything else is refused with `ERR_VALIDATION`."

    Design: Difficulty/non_linear_state_machine/membership_status_cycles_active_to_lapsed_and_back_to_active
    """
    set_clock(api, "2026-05-05T00:00:00Z")
    route = get_success_data(api.create_route(create_route_payload(), ADMIN))
    depot = get_success_data(
        api.create_drop_point(create_drop_point_payload(route["id"]), ADMIN)
    )
    member = get_success_data(
        api.create_member(
            create_member_payload(depot["id"], email="dues@coop.test", tier="PRO"),
            ADMIN,
        )
    )

    validate_error(
        api.pay_dues(member["id"], dues_payment_payload(18000, member["version"], 2), ADMIN),
        ApiErrorId.ERR_VALIDATION.value,
    )

    paid = validate_success(
        api.pay_dues(member["id"], dues_payment_payload(36000, member["version"], 2), ADMIN)
    )
    assert paid["status"] == "ACTIVE"
    assert paid["lifetime_dues_paid_cents"] == 36000
    assert_same_instant(
        paid["dues_paid_through"],
        shift_iso("2026-05-05T00:00:00Z", days=730),
        "dues_paid_through",
    )
    assert_same_instant(
        paid["dues_grace_until"],
        shift_iso("2026-05-05T00:00:00Z", days=744),
        "dues_grace_until",
    )
