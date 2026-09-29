"""Entry-fee line rounding and the digital image standard at its exact edges."""

from test_helpers import (
    ApiErrorId,
    create_artwork_image_payload,
    fixtures,
    get_success_data,
    make_artist_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# Four works whose combination exercises the base line, the additional line and
# the flat oversize surcharge at once. "Long Horizon" is the only oversize work:
# its greatest dimension is 150.0 cm.
FEE_WORKS = [
    {
        "title": "Ridge Line", "medium_category": "PAINTING",
        "width_cm": 90.0, "height_cm": 60.0, "depth_cm": 4.0, "weight_kg": 6.0,
    },
    {
        "title": "Salt Flat", "medium_category": "PHOTOGRAPHY",
        "width_cm": 100.0, "height_cm": 70.0, "depth_cm": 4.0, "weight_kg": 5.0,
    },
    {
        "title": "Long Horizon", "medium_category": "PAINTING",
        "width_cm": 150.0, "height_cm": 80.0, "depth_cm": 5.0, "weight_kg": 12.0,
    },
    {
        "title": "Small Study", "medium_category": "PHOTOGRAPHY",
        "width_cm": 60.0, "height_cm": 40.0, "depth_cm": 3.0, "weight_kg": 3.0,
    },
]

# 3,713 + 2 x 1,238 + 1 x 2,000.
EXPECTED_FEE_CENTS = 8189
# What a single rounding of the discounted total would have produced instead.
SINGLE_ROUNDING_FEE_CENTS = 8188


def _submit_four_work_member_entry():
    exhibition = fixtures.open_call()
    artist = fixtures.register_artist(member_status="MEMBER")
    entry, artworks = fixtures.setup_entry_with_works(
        exhibition["id"], artist, FEE_WORKS
    )
    pending = fixtures.submit_entry(entry["id"], artist)
    return exhibition, artist, entry, artworks, pending


def test_entry_fee_rounds_each_line_before_multiplying_and_summing(api):
    """PRD §3.3: "Two properties of this order are load-bearing: each of the two
    discounted lines is rounded to whole cents *before* being multiplied and
    summed, so a 4,500-cent base and a 1,500-cent additional line at a 0.175
    discount contribute 3,713 cents and 1,238 cents per additional work rather
    than a single rounding of the discounted total; and the oversize surcharge is
    never discounted, however the artist's membership stands."

    Design: Difficulty/combinatorial_formula/entry_fee_per_line_rounding_before_summation
    """
    _, _, _, _, pending = _submit_four_work_member_entry()

    assert pending["status"] == "PENDING_FEE"
    assert pending["works_count"] == 4
    assert pending["entry_fee_cents"] == EXPECTED_FEE_CENTS
    assert pending["entry_fee_cents"] != SINGLE_ROUNDING_FEE_CENTS, (
        "rounding the discounted total once instead of rounding each line "
        "produces a fee one cent lower and is wrong"
    )
    assert pending["fee_paid_cents"] == 0


def test_entry_fee_tender_one_cent_below_the_frozen_assessment_is_refused(api):
    """PRD §3.3: "With the fee frozen, the artist pays it by tendering an
    `amount_cents` that equals `entry_fee_cents` **exactly** — any other amount,
    over or under, is refused with `ERR_FEE_AMOUNT_MISMATCH`, and payment is only
    possible while the clock is still strictly before `call_closes_at`."

    Design: Difficulty/combinatorial_formula/entry_fee_per_line_rounding_before_summation
    """
    _, artist, entry, _, pending = _submit_four_work_member_entry()

    response = api.pay_entry_fee(
        entry["id"], {"amount_cents": SINGLE_ROUNDING_FEE_CENTS},
        make_artist_headers(artist["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FEE_AMOUNT_MISMATCH.value)

    after = validate_success(api.get_entry(entry["id"], make_artist_headers(artist["id"])))
    assert after["status"] == "PENDING_FEE"
    assert after["fee_paid_cents"] == 0
    assert after["entry_fee_cents"] == EXPECTED_FEE_CENTS


def test_entry_fee_tender_of_the_per_line_total_is_accepted(api):
    """PRD §3.3: "A successful payment records `fee_paid_cents`, advances the
    entry `PENDING_FEE → SUBMITTED`, and cascades: every work of the entry whose
    `status` is `DRAFT` advances to `SUBMITTED`, each such work's own `version`
    incrementing by 1 alongside the entry's."

    Design: Difficulty/combinatorial_formula/entry_fee_per_line_rounding_before_summation
    """
    _, artist, entry, _, _ = _submit_four_work_member_entry()

    paid = validate_success(
        api.pay_entry_fee(
            entry["id"], {"amount_cents": EXPECTED_FEE_CENTS},
            make_artist_headers(artist["id"]),
        )
    )

    assert paid["status"] == "SUBMITTED"
    assert paid["fee_paid_cents"] == EXPECTED_FEE_CENTS
    assert paid["entry_fee_cents"] == EXPECTED_FEE_CENTS


def _draft_entry_with_one_unimaged_work():
    exhibition = fixtures.open_call()
    artist = fixtures.register_artist()
    entry = fixtures.open_entry(exhibition["id"], artist)
    artwork = fixtures.attach_work(
        entry["id"], artist, with_primary_image=False, title="Ridge Line",
        medium_category="PAINTING",
    )
    return artist, entry, artwork


def test_image_exactly_at_every_standard_minimum_is_accepted(api):
    """PRD §3.2: "Five criteria constitute the digital standard, and any failure
    is refused with `ERR_IMAGE_STANDARD_VIOLATION`: the `format` must be `JPEG`
    or `PNG` (a `TIFF` is a valid enum member but does not meet the standard);
    `pixel_long_edge` must be at least 1200; `pixel_short_edge` must be at least
    800; `file_bytes` must be at most 8,388,608, that is 8 mebibytes; and
    `color_profile` must be `SRGB`, not `ADOBE_RGB` and not `CMYK`."

    Design: Difficulty/boundary_precision_check/image_pixel_long_edge_exactly_at_standard_minimum_accepted
    """
    artist, _, artwork = _draft_entry_with_one_unimaged_work()

    image = get_success_data(
        api.upload_artwork_image(
            artwork["id"],
            create_artwork_image_payload(
                role="PRIMARY", format="JPEG", pixel_long_edge=1200,
                pixel_short_edge=800, file_bytes=8388608, color_profile="SRGB",
            ),
            make_artist_headers(artist["id"]),
        ),
        expected_status=201,
    )

    assert image["pixel_long_edge"] == 1200
    assert image["pixel_short_edge"] == 800
    assert image["file_bytes"] == 8388608
    assert image["standard_ok"] is True, (
        "every persisted image reports standard_ok as true"
    )


def test_image_one_unit_outside_any_standard_minimum_is_refused(api):
    """PRD §3.2: "Five criteria constitute the digital standard, and any failure
    is refused with `ERR_IMAGE_STANDARD_VIOLATION`: the `format` must be `JPEG`
    or `PNG` (a `TIFF` is a valid enum member but does not meet the standard);
    `pixel_long_edge` must be at least 1200; `pixel_short_edge` must be at least
    800; `file_bytes` must be at most 8,388,608, that is 8 mebibytes; and
    `color_profile` must be `SRGB`, not `ADOBE_RGB` and not `CMYK`."

    Design: Difficulty/boundary_precision_check/image_pixel_long_edge_exactly_at_standard_minimum_accepted
    """
    artist, _, artwork = _draft_entry_with_one_unimaged_work()
    headers = make_artist_headers(artist["id"])

    get_success_data(
        api.upload_artwork_image(
            artwork["id"],
            create_artwork_image_payload(
                role="PRIMARY", pixel_long_edge=1200, pixel_short_edge=800,
                file_bytes=8388608,
            ),
            headers,
        ),
        expected_status=201,
    )

    refused = [
        {"pixel_long_edge": 1199, "pixel_short_edge": 800},
        {"pixel_long_edge": 1200, "pixel_short_edge": 799},
        {"pixel_long_edge": 1200, "pixel_short_edge": 800, "file_bytes": 8388609},
        {"pixel_long_edge": 1200, "pixel_short_edge": 800, "format": "TIFF"},
    ]
    for overrides in refused:
        response = api.upload_artwork_image(
            artwork["id"],
            create_artwork_image_payload(role="DETAIL", **overrides),
            headers,
        )
        validate_error(response, ApiErrorId.ERR_IMAGE_STANDARD_VIOLATION.value)

    stored, meta = validate_paginated(
        api.list_artwork_images(artwork["id"], headers)
    )
    assert meta["total_count"] == 1, "no violating upload may be stored"
    assert len(stored) == 1

    after = fixtures.read_artwork(artwork["id"])
    assert after["primary_image_count"] == 1
