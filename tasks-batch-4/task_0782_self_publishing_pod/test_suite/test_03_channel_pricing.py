"""Channel pricing: royalty snapshots (print/ebook variants), price bounds,
unsupported format types, effective-window overlap, and the OCC version guard.

Translates difficulty instances `dual_variant_calc/royalty_print_variant_vs_ebook_variant`,
`boundary_precision_check/ebook_rate_band_upper_boundary_999_vs_1000`, and
`resource_temporal_overlap/price_window_overlap_half_open_touching_allowed`, plus
corner instances from sections `calculations`, `validations`, and
`cross_cutting_complexity_layers`.
"""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId, make_publisher_headers,
    create_price_payload,
    create_publisher, create_title, create_amz_channel, create_igs_channel,
    create_print_format, create_ebook_format, create_price, current_version,
)


def _base_print(api):
    channel = create_amz_channel(api)
    pub = create_publisher(api)
    title = create_title(api, pub["id"])
    fmt = create_print_format(api, pub["id"], title["id"])
    return channel, pub, title, fmt


def _base_ebook(api, channel=None):
    channel = channel or create_amz_channel(api)
    pub = create_publisher(api)
    title = create_title(api, pub["id"])
    fmt = create_ebook_format(api, pub["id"], title["id"])
    return channel, pub, title, fmt


# --- dual_variant_calc: print vs ebook royalty -------------------------------

def test_royalty_print_variant_subtracts_print_cost(api):
    """PRD 3.5: "the royalty per unit is the list price multiplied by one minus
    that discount, minus the format's print_cost_cents, the whole expression
    rounded half up."

    Design: Difficulty/dual_variant_calc/royalty_print_variant_vs_ebook_variant
    """
    channel, pub, title, fmt = _base_print(api)
    price = create_price(api, pub["id"], fmt["id"], channel["id"], list_price_cents=1500)
    assert price["royalty_per_unit_cents"] == 575, \
        f"print royalty expected 575, got {price['royalty_per_unit_cents']}"


def test_royalty_ebook_variant_differs_from_print(api):
    """PRD 3.5: "when list_price_cents is greater than or equal to the low
    threshold and less than or equal to the high threshold, the rate is
    ebook_high_rate and a delivery fee equal to the format's file_size_mb
    multiplied by the channel's delivery_fee_per_mb_cents, rounded half up, is
    charged". PRD 3.5: "The ebook royalty per unit is then the list price
    multiplied by the selected rate, minus the delivery fee, rounded half up."

    Design: Difficulty/dual_variant_calc/royalty_print_variant_vs_ebook_variant
    """
    channel = create_amz_channel(api)
    pub = create_publisher(api)
    title = create_title(api, pub["id"])
    fmt_print = create_print_format(api, pub["id"], title["id"])
    fmt_ebook = create_ebook_format(api, pub["id"], title["id"], file_size_mb=2.0)
    price_print = create_price(api, pub["id"], fmt_print["id"], channel["id"], list_price_cents=1500)
    price_ebook = create_price(api, pub["id"], fmt_ebook["id"], channel["id"], list_price_cents=999)
    assert price_ebook["royalty_per_unit_cents"] == 669, \
        f"ebook royalty expected 669, got {price_ebook['royalty_per_unit_cents']}"
    assert price_print["royalty_per_unit_cents"] != price_ebook["royalty_per_unit_cents"], \
        "print and ebook variants must produce different royalties"


# --- boundary_precision_check: ebook band upper boundary ---------------------

def test_ebook_at_band_upper_boundary_uses_high_rate(api):
    """PRD 3.5: "which runs from ebook_rate_low_threshold_cents to
    ebook_rate_high_threshold_cents inclusive of both ends: when list_price_cents
    is greater than or equal to the low threshold and less than or equal to the
    high threshold, the rate is ebook_high_rate and a delivery fee equal to the
    format's file_size_mb multiplied by the channel's delivery_fee_per_mb_cents,
    rounded half up, is charged".

    Design: Difficulty/boundary_precision_check/ebook_rate_band_upper_boundary_999_vs_1000
    """
    channel, pub, title, fmt = _base_ebook(api)
    price = create_price(api, pub["id"], fmt["id"], channel["id"], list_price_cents=999)
    assert price["royalty_per_unit_cents"] == 669, \
        f"at boundary 999 expected 669, got {price['royalty_per_unit_cents']}"


def test_ebook_above_band_boundary_uses_low_rate(api):
    """PRD 3.5: "when the list price falls outside that band, the rate is
    ebook_low_rate and no delivery fee is charged. The ebook royalty per unit is
    then the list price multiplied by the selected rate, minus the delivery fee,
    rounded half up."

    Design: Difficulty/boundary_precision_check/ebook_rate_band_upper_boundary_999_vs_1000
    """
    channel, pub, title, fmt = _base_ebook(api)
    price = create_price(api, pub["id"], fmt["id"], channel["id"], list_price_cents=1000)
    assert price["royalty_per_unit_cents"] == 350, \
        f"above boundary at 1000 expected 350, got {price['royalty_per_unit_cents']}"


# --- corner: print expanded-reach variant selection --------------------------

def test_print_royalty_expanded_reach_uses_expanded_discount(api):
    """PRD 3.5: "For a PRINT format, the applicable wholesale discount is the
    channel's distribution_discount_expanded when expanded_reach is true and its
    distribution_discount_standard otherwise; the royalty per unit is the list
    price multiplied by one minus that discount, minus the format's
    print_cost_cents, the whole expression rounded half up."

    Design: Corner/calculations/print_royalty_expanded_reach_variant_selection
    """
    channel, pub, title, fmt = _base_print(api)
    price = create_price(api, pub["id"], fmt["id"], channel["id"],
                         list_price_cents=1500, expanded_reach=True)
    assert price["royalty_per_unit_cents"] == 275, \
        f"expanded-reach royalty expected 275, got {price['royalty_per_unit_cents']}"


# --- corner: fiscal bounds & channel format support --------------------------

def test_price_below_channel_minimum_rejected(api):
    """PRD 3.5: "then the list_price_cents must fall within the channel's
    inclusive min_list_price_cents to max_list_price_cents range, else
    ERR_PRICE_OUT_OF_BOUNDS (HTTP 422)".

    Design: Corner/validations/price_out_of_bounds_returns_price_out_of_bounds
    """
    channel, pub, title, fmt = _base_print(api)
    payload = create_price_payload(current_version(api, fmt["id"]), channel["id"], 50)
    validate_error(
        api.create_price(fmt["id"], payload, make_publisher_headers(pub["id"])),
        ApiErrorId.ERR_PRICE_OUT_OF_BOUNDS,
    )


def test_price_on_unsupported_format_type_rejected(api):
    """PRD 3.5: "then the channel must actually distribute this format_type, i.e.
    the format's type must appear in the channel's supports_formats, else
    ERR_CHANNEL_FORMAT_UNSUPPORTED (HTTP 422)".

    Design: Corner/validations/price_on_unsupported_format_returns_channel_format_unsupported
    """
    channel = create_igs_channel(api)  # PRINT-only channel
    pub = create_publisher(api)
    title = create_title(api, pub["id"])
    fmt = create_ebook_format(api, pub["id"], title["id"])
    payload = create_price_payload(current_version(api, fmt["id"]), channel["id"], 999)
    validate_error(
        api.create_price(fmt["id"], payload, make_publisher_headers(pub["id"])),
        ApiErrorId.ERR_CHANNEL_FORMAT_UNSUPPORTED,
    )


# --- resource_temporal_overlap: half-open price windows ----------------------

def test_touching_price_window_accepted(api):
    """PRD 3.5: "windows are half-open, so two windows that merely touch at an
    endpoint do not overlap, but any true overlap yields
    ERR_PRICE_WINDOW_OVERLAP (HTTP 409)".

    Design: Difficulty/resource_temporal_overlap/price_window_overlap_half_open_touching_allowed
    """
    channel, pub, title, fmt = _base_print(api)
    create_price(api, pub["id"], fmt["id"], channel["id"], list_price_cents=1500,
                 effective_from="2026-01-01T00:00:00Z", effective_to="2026-04-01T00:00:00Z")
    p2 = create_price(api, pub["id"], fmt["id"], channel["id"], list_price_cents=1600,
                      effective_from="2026-04-01T00:00:00Z", effective_to="2026-07-01T00:00:00Z")
    assert p2["status"] == "ACTIVE", "an adjacent touching window must be accepted"


def test_overlapping_price_window_rejected(api):
    """PRD 3.5: "then the new window must not overlap an existing ACTIVE price for
    the same format, channel, and territory - windows are half-open, so two
    windows that merely touch at an endpoint do not overlap, but any true overlap
    yields ERR_PRICE_WINDOW_OVERLAP (HTTP 409)".

    Design: Difficulty/resource_temporal_overlap/price_window_overlap_half_open_touching_allowed
    """
    channel, pub, title, fmt = _base_print(api)
    create_price(api, pub["id"], fmt["id"], channel["id"], list_price_cents=1500,
                 effective_from="2026-01-01T00:00:00Z", effective_to="2026-04-01T00:00:00Z")
    create_price(api, pub["id"], fmt["id"], channel["id"], list_price_cents=1600,
                 effective_from="2026-04-01T00:00:00Z", effective_to="2026-07-01T00:00:00Z")
    payload = create_price_payload(
        current_version(api, fmt["id"]), channel["id"], 1700,
        effective_from="2026-03-01T00:00:00Z", effective_to="2026-06-01T00:00:00Z",
    )
    validate_error(
        api.create_price(fmt["id"], payload, make_publisher_headers(pub["id"])),
        ApiErrorId.ERR_PRICE_WINDOW_OVERLAP,
    )


# --- cross_cutting: optimistic concurrency on Format.version -----------------

def test_price_create_stale_format_version_conflict(api):
    """PRD 2.7: "Before the price is created, the server compares
    expected_format_version to the format's current version. If they do not
    match - meaning another writer has advanced the format's version since the
    client last read it, for instance by creating a newer default price that
    superseded the client's expected base - the create is rejected with
    ERR_STALE_FORMAT_VERSION (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/price_create_stale_format_version_conflict
    """
    channel, pub, title, fmt = _base_print(api)
    headers = make_publisher_headers(pub["id"])
    stale_version = fmt["version"]  # captured before any price create
    first = get_success_data(api.create_price(
        fmt["id"],
        create_price_payload(stale_version, channel["id"], 1500, territory="US",
                             effective_from="2026-02-01T00:00:00Z"),
        headers,
    ))
    assert first["status"] == "ACTIVE", "the first create must succeed"
    # Second create still carries the now-stale version.
    second = api.create_price(
        fmt["id"],
        create_price_payload(stale_version, channel["id"], 1600, territory="UK",
                             effective_from="2026-02-01T00:00:00Z"),
        headers,
    )
    validate_error(second, ApiErrorId.ERR_STALE_FORMAT_VERSION)
