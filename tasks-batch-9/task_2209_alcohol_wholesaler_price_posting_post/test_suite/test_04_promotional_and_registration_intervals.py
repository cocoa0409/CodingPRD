"""Combination floor bands, the cooldown buffer, and closed brand registration intervals."""

from test_helpers import (
    api_client,
    assert_brand,
    assert_combination_sale,
    create_brand_payload,
    create_combination_sale_payload,
    new_combination,
    read_brand,
    read_combination,
    regulator_headers,
    setup_draft_schedule,
    setup_licensee_base,
    validate_error,
    validate_paginated,
    validate_success,
)

COMBINATION_ITEM_SPECS = [
    {
        "size_ml": 750,
        "bottles_per_case": 12,
        "case_price_cents": 120_000,
        "unit_price_cents": 11_000,
    },
    {
        "size_ml": 375,
        "bottles_per_case": 24,
        "case_price_cents": 30_000,
        "unit_price_cents": 1_500,
    },
]

INCUMBENT_BRAND_INTERVAL = {
    "registration_effective_from": "2026-01-01T00:00:00Z",
    "registration_expires_on": "2026-06-30T23:59:59.999Z",
}


def _two_item_draft_scene():
    """A draft schedule holding a 120,000 cent item and a 30,000 cent item."""
    scene = setup_licensee_base()
    return setup_draft_schedule(scene, item_specs=COMBINATION_ITEM_SPECS)


def test_combination_floor_is_the_plain_sum_of_the_member_case_prices():
    """Two members at 120,000 and 30,000 cents give a pre-discount floor of 150,000.

    PRD §3.5: "First, `floor_price_cents` is the plain sum of `case_price_cents` across
    every member item."

    Design: Difficulty/combinatorial_formula/combination_sale_band_selected_on_pre_discount_floor_not_discounted_price
    """
    scene = _two_item_draft_scene()
    member_ids = [item["id"] for item in scene["items"]]

    combination = new_combination(
        scene["schedule"]["id"], member_ids, 135_000, scene["agent_headers"]
    )

    assert_combination_sale(combination)
    assert combination["member_item_ids"] == member_ids
    assert combination["floor_price_cents"] == 150_000


def test_combination_band_is_keyed_on_the_pre_discount_floor_not_the_discounted_value():
    """A floor of exactly 150,000 lands in the ten percent band, so 135,000 is admissible.

    PRD §3.5: "Keying the band on the pre-discount floor is load-bearing: a
    `floor_price_cents` of exactly 150,000 lands in the ten percent band and yields a
    `min_allowed_price_cents` of 135,000; keying the band on the discounted value would
    have selected the five percent band and produced 142,500, which is not the rule."

    Design: Difficulty/combinatorial_formula/combination_sale_band_selected_on_pre_discount_floor_not_discounted_price
    """
    scene = _two_item_draft_scene()
    member_ids = [item["id"] for item in scene["items"]]

    combination = new_combination(
        scene["schedule"]["id"], member_ids, 135_000, scene["agent_headers"]
    )

    assert combination["min_allowed_price_cents"] == 135_000
    assert combination["min_allowed_price_cents"] != 142_500
    assert combination["combined_case_price_cents"] == 135_000
    assert combination["status"] == "ACTIVE"

    stored = read_combination(combination["id"])
    assert stored["floor_price_cents"] == 150_000
    assert stored["min_allowed_price_cents"] == 135_000


def _incumbent_combination_scene():
    """A draft schedule whose wholesaler already runs a November promotional window."""
    scene = _two_item_draft_scene()
    member_ids = [item["id"] for item in scene["items"]]
    scene["member_ids"] = member_ids
    scene["incumbent"] = new_combination(
        scene["schedule"]["id"],
        member_ids,
        135_000,
        scene["agent_headers"],
        promo_starts_at="2026-11-01T00:00:00Z",
        promo_ends_at="2026-11-10T00:00:00Z",
    )
    return scene


def test_requested_window_whose_buffered_end_passes_the_incumbent_start_conflicts():
    """One millisecond of buffered overlap reaching backwards is still a cooldown conflict.

    PRD §3.5: "A requested window conflicts with an existing `ACTIVE` combination sale of
    the same wholesaler when **both** of these hold: the requested `promo_starts_at` is
    strictly before that existing window's `promo_ends_at` advanced by the buffer, and
    that existing window's `promo_starts_at` is strictly before the requested
    `promo_ends_at` advanced by the buffer."

    Design: Difficulty/resource_temporal_overlap/combination_window_cooldown_conflicts_backward_through_the_buffered_requested_end
    """
    scene = _incumbent_combination_scene()

    response = api_client.create_combination_sale(
        create_combination_sale_payload(
            scene["schedule"]["id"],
            scene["member_ids"],
            135_000,
            promo_starts_at="2026-10-01T00:00:00.000Z",
            promo_ends_at="2026-10-25T00:00:00.001Z",
        ),
        scene["agent_headers"],
    )

    validate_error(response, "ERR_COMBINATION_COOLDOWN_VIOLATION", 409)

    incumbent = read_combination(scene["incumbent"]["id"])
    assert incumbent["status"] == "ACTIVE"
    assert incumbent["promo_starts_at"] == "2026-11-01T00:00:00.000Z"

    listing = api_client.list_combination_sales(
        regulator_headers(),
        params={"schedule_id": scene["schedule"]["id"], "status": "ACTIVE"},
    )
    data, meta = validate_paginated(listing)
    assert meta["total_count"] == 1
    assert len(data) == 1


def test_requested_window_whose_buffered_end_meets_the_incumbent_start_is_admitted():
    """Both cooldown comparisons are strict, so a buffered end that merely touches passes.

    PRD §3.5: "Both comparisons are strict, so a requested window beginning exactly at an
    existing window's end plus the buffer does not conflict."

    Design: Difficulty/resource_temporal_overlap/combination_window_cooldown_conflicts_backward_through_the_buffered_requested_end
    """
    scene = _incumbent_combination_scene()

    response = api_client.create_combination_sale(
        create_combination_sale_payload(
            scene["schedule"]["id"],
            scene["member_ids"],
            135_000,
            promo_starts_at="2026-10-01T00:00:00.000Z",
            promo_ends_at="2026-10-25T00:00:00.000Z",
        ),
        scene["agent_headers"],
    )

    created = validate_success(response, 201)
    assert_combination_sale(created)
    assert created["status"] == "ACTIVE"
    assert created["promo_ends_at"] == "2026-10-25T00:00:00.000Z"
    assert created["floor_price_cents"] == 150_000
    assert created["min_allowed_price_cents"] == 135_000

    incumbent = read_combination(scene["incumbent"]["id"])
    assert incumbent["status"] == "ACTIVE"
    assert incumbent["promo_starts_at"] == "2026-11-01T00:00:00.000Z"

    listing = api_client.list_combination_sales(
        regulator_headers(),
        params={"schedule_id": scene["schedule"]["id"], "status": "ACTIVE"},
    )
    _data, meta = validate_paginated(listing)
    assert meta["total_count"] == 2


def _incumbent_brand_scene():
    """A wholesaler holding one approved registration that expires mid-year."""
    return setup_licensee_base(brand_overrides=INCUMBENT_BRAND_INTERVAL)


def test_registration_touching_the_incumbent_expiry_instant_overlaps():
    """Registration intervals are closed, so sharing the expiry instant is an overlap.

    PRD §3.2: "Because these are closed intervals, two registrations conflict when the
    requested `registration_effective_from` is at or before an existing registration's
    `registration_expires_on` **and** that existing registration's
    `registration_effective_from` is at or before the requested
    `registration_expires_on` — intervals that merely touch at an endpoint do overlap."

    Design: Difficulty/resource_temporal_overlap/brand_registration_closed_intervals_collide_on_a_single_shared_endpoint_instant
    """
    scene = _incumbent_brand_scene()

    response = api_client.create_brand(
        create_brand_payload(
            scene["wholesaler"]["id"],
            registration_effective_from="2026-06-30T23:59:59.999Z",
            registration_expires_on="2026-12-31T23:59:59.999Z",
        ),
        scene["agent_headers"],
    )

    validate_error(response, "ERR_BRAND_REGISTRATION_OVERLAP", 409)

    incumbent = read_brand(scene["brand"]["id"])
    assert incumbent["registration_status"] == "APPROVED"
    assert incumbent["registration_expires_on"] == "2026-06-30T23:59:59.999Z"

    listing = api_client.list_brands(
        regulator_headers(), params={"wholesaler_id": scene["wholesaler"]["id"]}
    )
    _data, meta = validate_paginated(listing)
    assert meta["total_count"] == 1


def test_registration_starting_one_millisecond_after_the_expiry_is_admitted():
    """Move the requested start off the shared instant and the timeline is free again.

    PRD §3.2: "The new registration begins in `PENDING` with `rejection_reason` unset."

    Design: Difficulty/resource_temporal_overlap/brand_registration_closed_intervals_collide_on_a_single_shared_endpoint_instant
    """
    scene = _incumbent_brand_scene()

    response = api_client.create_brand(
        create_brand_payload(
            scene["wholesaler"]["id"],
            registration_effective_from="2026-07-01T00:00:00.000Z",
            registration_expires_on="2026-12-31T23:59:59.999Z",
        ),
        scene["agent_headers"],
    )

    created = validate_success(response, 201)
    assert_brand(created)
    assert created["registration_status"] == "PENDING"
    assert created["registration_effective_from"] == "2026-07-01T00:00:00.000Z"
    assert created["registration_expires_on"] == "2026-12-31T23:59:59.999Z"

    incumbent = read_brand(scene["brand"]["id"])
    assert incumbent["registration_status"] == "APPROVED"
    assert incumbent["registration_expires_on"] == "2026-06-30T23:59:59.999Z"

    listing = api_client.list_brands(
        regulator_headers(), params={"wholesaler_id": scene["wholesaler"]["id"]}
    )
    _data, meta = validate_paginated(listing)
    assert meta["total_count"] == 2
