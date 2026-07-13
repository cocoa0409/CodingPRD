"""Print manufacturing cost, format version counter, and format listing.

Translates difficulty instance `combinatorial_formula/print_cost_tiered_...` and
corner instances from sections `cross_cutting_complexity_layers` and `endpoints`.
"""
from test_helpers import (
    validate_success, validate_paginated, get_success_data,
    TEST_USERS, make_publisher_headers,
    create_print_format_payload,
    create_publisher, create_title, create_amz_channel, create_print_format,
    create_ebook_format, create_price,
)

ADMIN = TEST_USERS["admin_headers"]


def test_print_cost_bw_standard_trim(api):
    """PRD 3.2: "the cost is 85 cents, plus the page count multiplied by the
    color's per-page rate, plus the page count multiplied by the large-trim
    surcharge (which is 0.5 when the trim is large and 0 otherwise), with the
    total sum rounded half up to a whole number of cents."
    PRD 3.2: "1.2 cents per page for BW".

    Design: Difficulty/combinatorial_formula/print_cost_tiered_rate_plus_trim_surcharge
    """
    pub = create_publisher(api)
    title = create_title(api, pub["id"])
    payload = create_print_format_payload(trim_size="6x9", interior_color="BW", page_count=200)
    data = validate_success(
        api.create_format(title["id"], payload, make_publisher_headers(pub["id"])), 201
    )
    assert data["print_cost_cents"] == 325, f"expected 325, got {data['print_cost_cents']}"


def test_print_cost_premium_color_large_trim(api):
    """PRD 3.2: "the cost is 85 cents, plus the page count multiplied by the
    color's per-page rate, plus the page count multiplied by the large-trim
    surcharge (which is 0.5 when the trim is large and 0 otherwise), with the
    total sum rounded half up to a whole number of cents."
    PRD 3.2: "10.0 cents per page for PREMIUM_COLOR. The trim surcharge applies
    only when trim_size is in the large-trim band - that is, 7x10 or 8.5x11 -
    and adds 0.5 cents for each page".

    Design: Difficulty/combinatorial_formula/print_cost_tiered_rate_plus_trim_surcharge
    """
    pub = create_publisher(api)
    title = create_title(api, pub["id"])
    payload = create_print_format_payload(
        trim_size="8.5x11", interior_color="PREMIUM_COLOR", page_count=100
    )
    data = validate_success(
        api.create_format(title["id"], payload, make_publisher_headers(pub["id"])), 201
    )
    assert data["print_cost_cents"] == 1135, f"expected 1135, got {data['print_cost_cents']}"


def test_format_version_increments_on_price_create(api):
    """PRD 2.4: "an integer version that starts at 1 and increments by 1 on each
    mutation of that row."
    PRD 3.5: "Creating any price increments Format.version by 1".

    Design: Corner/cross_cutting_complexity_layers/format_version_increments_on_price_create
    """
    channel = create_amz_channel(api)
    pub = create_publisher(api)
    title = create_title(api, pub["id"])
    fmt = create_print_format(api, pub["id"], title["id"])
    assert fmt["version"] == 1, "format version must start at 1 on create"
    create_price(api, pub["id"], fmt["id"], channel["id"])
    refetched = get_success_data(api.get_format(fmt["id"], make_publisher_headers(pub["id"])))
    assert refetched["version"] == 2, f"expected version 2 after one price, got {refetched['version']}"


def test_list_formats_by_title_paginated(api):
    """PRD 2.3: "Each list response reports limit, offset, total_count (the
    number of rows matching the query before pagination), and has_more (true
    when unreturned rows remain beyond the current window) inside the meta
    object."

    Design: Corner/endpoints/list_formats_by_title_paginated
    """
    pub = create_publisher(api)
    title = create_title(api, pub["id"])
    create_print_format(api, pub["id"], title["id"])
    create_ebook_format(api, pub["id"], title["id"])
    headers = make_publisher_headers(pub["id"])
    data, meta = validate_paginated(
        api.list_formats(headers, params={"title_id": title["id"], "limit": 1, "offset": 0})
    )
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, "has_more must be true when more than one format exists"
    assert len(data) == 1, "limit=1 must return exactly one row"
