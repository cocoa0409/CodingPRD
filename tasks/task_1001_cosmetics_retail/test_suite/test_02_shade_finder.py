"""The shade finder: candidacy filters, scoring and the empty-pool fallback."""

from test_helpers import (
    ApiErrorId,
    assert_variant,
    new_customer,
    new_lot,
    new_product,
    new_store,
    new_variant,
    make_customer_headers,
    shade_request_payload,
    validate_error,
    validate_success,
)


def test_shade_finder_returns_highest_scoring_variant(api, admin_headers):
    """PRD §3.3: "Surviving candidates are scored. Each starts from a base of 100
    points. Ten points are then deducted for each step of depth difference between the
    candidate and the request — a two-step difference costs twenty points. Twenty-five
    points are added when the candidate's `undertone` equals the requested undertone,
    and a further fifteen points are added when the candidate's `finish` equals the
    requested `finish_pref`. The highest score wins."
    PRD §3.3: "When two candidates score identically, the one whose depth is closer to
    the request wins; if they are still tied, the older record — the earlier
    `created_at` — wins. Identifiers are never used to break the tie. Exactly one
    variant is returned."

    Design: Corner/calculations/shade_match_ranks_by_score_then_depth_then_created_at
    """
    product = new_product(name="Foundation", base_price_cents=4500)
    # 100 - 0 + 25 + 15 = 140
    v_a = new_variant(
        product["id"], shade_name="Sand", shade_code="F-06W", finish="MATTE",
        undertone="WARM", depth_index=6, price_cents=4500,
    )
    # 100 - 10 + 25 + 15 = 130
    v_b = new_variant(
        product["id"], shade_name="Beige", shade_code="F-05W", finish="MATTE",
        undertone="WARM", depth_index=5, price_cents=4500,
    )
    # 100 - 0 + 0 + 15 = 115
    v_c = new_variant(
        product["id"], shade_name="Shell", shade_code="F-06C", finish="MATTE",
        undertone="COOL", depth_index=6, price_cents=4500,
    )
    customer = new_customer()

    resp = api.recommend_shade(
        shade_request_payload("WARM", 6, "MATTE"),
        make_customer_headers(customer["id"]),
    )
    best = validate_success(resp, 200)

    assert_variant(best)
    assert best["id"] == v_a["id"], (
        f"score 140 must beat 130 ({v_b['id']}) and 115 ({v_c['id']})"
    )
    assert resp.json()["response_type"] == "object", "exactly one variant is returned"


def test_shade_finder_excludes_discontinued_and_gated_variants(api, admin_headers):
    """PRD §3.3: "A variant is a candidate only if its `status` is `ACTIVE`, only if
    its `launch_status` is either `NOT_LIMITED` or `PUBLIC` (a shade still inside a
    tier-gated launch window is never recommended), and only if its `depth_index` sits
    within two steps of the requested depth in either direction — a difference of
    exactly two is still inside the tolerance."

    Design: Corner/calculations/shade_match_excludes_discontinued_and_unopened_launch_variants
    """
    product = new_product(name="Foundation", base_price_cents=4500)

    # Would score 140, but is DISCONTINUED.
    v_disc = new_variant(
        product["id"], shade_name="Disc", shade_code="F-D", finish="MATTE",
        undertone="WARM", depth_index=6, price_cents=4500,
    )
    validate_success(
        api.update_variant(v_disc["id"], {"status": "DISCONTINUED"}, admin_headers)
    )

    # Would score 140, but its launch is still SCHEDULED at the boot clock.
    v_ltd = validate_success(
        api.create_variant(
            product["id"],
            {
                "shade_name": "Ltd", "shade_code": "F-L", "finish": "MATTE",
                "undertone": "WARM", "depth_index": 6, "price_cents": 4500,
                "is_limited_launch": True,
                "launch_open_rouge_at": "2026-07-01T00:00:00Z",
                "launch_open_vib_at": "2026-07-02T00:00:00Z",
                "launch_open_public_at": "2026-07-03T00:00:00Z",
            },
            admin_headers,
        ),
        201,
    )

    # Scores 100: right depth, wrong undertone and finish — but eligible.
    v_ok = new_variant(
        product["id"], shade_name="Ok", shade_code="F-O", finish="DEWY",
        undertone="NEUTRAL", depth_index=6, price_cents=4500,
    )
    customer = new_customer()

    best = validate_success(
        api.recommend_shade(
            shade_request_payload("WARM", 6, "MATTE"),
            make_customer_headers(customer["id"]),
        )
    )

    assert best["id"] == v_ok["id"], "only the ACTIVE, NOT_LIMITED variant is a candidate"
    assert best["id"] != v_disc["id"], "a DISCONTINUED variant is never recommended"
    assert best["id"] != v_ltd["id"], "a SCHEDULED launch variant is never recommended"


def test_shade_finder_store_filter_drops_unstocked_variants(api, admin_headers):
    """PRD §3.3: "When a `store_id` is supplied, the variant additionally needs an
    inventory lot at that store whose `on_hand_units` less its `launch_reserved_units`
    is at least one unit."

    Design: Corner/calculations/shade_match_store_filter_excludes_out_of_stock_variants
    """
    store = new_store()
    product = new_product(name="Foundation", base_price_cents=4500)
    v_hi = new_variant(
        product["id"], shade_name="Hi", shade_code="F-HI", finish="MATTE",
        undertone="WARM", depth_index=6, price_cents=4500,
    )  # would score 140
    v_lo = new_variant(
        product["id"], shade_name="Lo", shade_code="F-LO", finish="DEWY",
        undertone="NEUTRAL", depth_index=6, price_cents=4500,
    )  # scores 100
    new_lot(store["id"], v_hi["id"], units_received=0)
    new_lot(store["id"], v_lo["id"], units_received=5)
    customer = new_customer()
    headers = make_customer_headers(customer["id"])

    filtered = validate_success(
        api.recommend_shade(
            shade_request_payload("WARM", 6, "MATTE", store_id=store["id"]), headers
        )
    )
    assert filtered["id"] == v_lo["id"], (
        "the higher-scoring variant has no drawable unit at this store"
    )

    unfiltered = validate_success(
        api.recommend_shade(shade_request_payload("WARM", 6, "MATTE"), headers)
    )
    assert unfiltered["id"] == v_hi["id"], (
        "without store_id the stock filter does not apply, so the 140 variant wins"
    )


def test_shade_finder_empty_candidate_set_returns_no_shade_match(api):
    """PRD §3.3: "When a `store_id` is supplied, the variant additionally needs an
    inventory lot at that store whose `on_hand_units` less its `launch_reserved_units`
    is at least one unit. If nothing survives the filter, the request fails with
    `ERR_NO_SHADE_MATCH` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/shade_finder_with_empty_candidate_set_returns_no_shade_match
    """
    product = new_product(name="Foundation", base_price_cents=4500)
    new_variant(
        product["id"], shade_name="Porcelain", shade_code="F-02A", finish="MATTE",
        undertone="COOL", depth_index=2, price_cents=4500,
    )
    new_variant(
        product["id"], shade_name="Ivory", shade_code="F-02B", finish="DEWY",
        undertone="WARM", depth_index=2, price_cents=4500,
    )
    customer = new_customer()

    # |2 - 9| == 7, far outside the two-step tolerance: nothing survives the filter.
    resp = api.recommend_shade(
        shade_request_payload("WARM", 9, "MATTE"),
        make_customer_headers(customer["id"]),
    )

    validate_error(resp, ApiErrorId.ERR_NO_SHADE_MATCH.value)


def test_shade_finder_depth_difference_of_exactly_two_still_matches(api):
    """PRD §3.3: "A variant is a candidate only if its `status` is `ACTIVE`, only if
    its `launch_status` is either `NOT_LIMITED` or `PUBLIC` (a shade still inside a
    tier-gated launch window is never recommended), and only if its `depth_index` sits
    within two steps of the requested depth in either direction — a difference of
    exactly two is still inside the tolerance."

    The same catalogue that yields ERR_NO_SHADE_MATCH at depth 9 must answer at depth
    4: the empty-pool fallback is a boundary on the candidate set, not a blanket
    refusal.

    Design: Difficulty/boundary_precision_check/shade_finder_with_empty_candidate_set_returns_no_shade_match
    """
    product = new_product(name="Foundation", base_price_cents=4500)
    new_variant(
        product["id"], shade_name="Porcelain", shade_code="F-02A", finish="MATTE",
        undertone="COOL", depth_index=2, price_cents=4500,
    )
    new_variant(
        product["id"], shade_name="Ivory", shade_code="F-02B", finish="DEWY",
        undertone="WARM", depth_index=2, price_cents=4500,
    )
    customer = new_customer()
    headers = make_customer_headers(customer["id"])

    resp = api.recommend_shade(shade_request_payload("WARM", 4, "MATTE"), headers)
    best = validate_success(resp, 200)

    assert best["depth_index"] == 2, "|2 - 4| == 2 is inside the tolerance"
    assert_variant(best)

    # And one step further out the pool empties again.
    validate_error(
        api.recommend_shade(shade_request_payload("WARM", 5, "MATTE"), headers),
        ApiErrorId.ERR_NO_SHADE_MATCH.value,
    )
