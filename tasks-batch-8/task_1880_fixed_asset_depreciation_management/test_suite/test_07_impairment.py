"""Impairment review workflow: write-down cascade, open-window exclusivity,
zero-write-down boundary, terminal lockdown, and OCC version pinning."""
from test_helpers import (
    ACCT,
    CTRL,
    ApiErrorId,
    create_and_post_run,
    create_class,
    create_in_service_asset,
    create_open_review,
    current_asset_version,
    refresh_asset,
    validate_error,
    validate_paginated,
    validate_success,
)


def _nbv_110000_setup(api, tag="A-700"):
    """120000-cost, 12-month-life asset, in service 2026-01-10, run 2026-01
    posted (BOOK accumulated 10000, net book value 110000), OPEN manual review.
    Returns (asset, review, asset_version)."""
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag=tag, description="Oven line",
        acquisition_cost_cents=120000, useful_life_months=12,
    )
    create_and_post_run("2026-01")
    version = current_asset_version(asset["id"])
    review = create_open_review(asset["id"], indicator="MARKET_DECLINE")
    return asset, review, version


def test_confirm_posts_write_down_onto_asset(api):
    """PRD §3.4: "The write-down is computed as `net_book_value_cents` minus
    `recoverable_value_cents`; if that difference is zero or negative, there is
    nothing to write down, the confirm is rejected with
    `ERR_NO_IMPAIRMENT_INDICATED` (HTTP 422), and the review should be dismissed
    instead."
    PRD §3.4: "A successful confirm writes `write_down_cents` onto the review,
    moves it from `OPEN` to the terminal status `WRITTEN_DOWN`, and cascades onto
    the asset in one atomic step: the asset's `impairment_total_cents` increases
    by `write_down_cents`, its `net_book_value_cents` is recomputed, its
    `version` increments by one, and its remaining depreciable basis —
    acquisition cost minus `salvage_value_cents` minus `accumulated_book_cents`
    minus the new `impairment_total_cents` — is re-evaluated."

    Design: Difficulty/transitive_cascade/impairment_confirm_three_link_cascade
    """
    asset, review, version = _nbv_110000_setup(api)
    confirmed = validate_success(
        api.confirm_impairment_review(
            review["id"],
            {"recoverable_value_cents": 0, "expected_asset_version": version},
            CTRL,
        ),
        200,
    )
    assert confirmed["status"] == "WRITTEN_DOWN"
    assert confirmed["write_down_cents"] == 110000, "NBV 110000 - recoverable 0"

    after = refresh_asset(asset["id"])
    assert after["impairment_total_cents"] == 110000
    assert after["net_book_value_cents"] == 0
    assert after["version"] == version + 1


def test_zero_remaining_basis_auto_fully_depreciates_asset(api):
    """PRD §3.4: "If the remaining basis is zero or negative, the asset
    automatically transitions from `IN_SERVICE` to `FULLY_DEPRECIATED`."
    PRD §3.3: "the asset must be `IN_SERVICE` (assets in `DRAFT`,
    `FULLY_DEPRECIATED`, or `DISPOSED` are excluded)"

    Design: Difficulty/transitive_cascade/impairment_confirm_three_link_cascade
    """
    asset, review, version = _nbv_110000_setup(api)
    validate_success(
        api.confirm_impairment_review(
            review["id"],
            {"recoverable_value_cents": 0, "expected_asset_version": version},
            CTRL,
        ),
        200,
    )

    after = refresh_asset(asset["id"])
    assert after["status"] == "FULLY_DEPRECIATED", (
        "auto-transition fired by the basis recompute, not by any asset call"
    )

    run = create_and_post_run("2026-02")
    assert run["entries_created_count"] == 0, (
        "a FULLY_DEPRECIATED asset is ineligible in later runs"
    )


def test_second_open_review_rejected(api):
    """PRD §3.4: "At most one review per asset may be `OPEN` at a time — a second
    open attempt is rejected with `ERR_IMPAIRMENT_REVIEW_OPEN`."

    Design: Difficulty/resource_temporal_overlap/impairment_review_open_window_exclusivity
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-960", description="Reviewed asset",
        acquisition_cost_cents=400000,
    )
    first = create_open_review(asset["id"], indicator="OBSOLESCENCE")
    assert first["status"] == "OPEN"

    resp = api.create_impairment_review(
        {"asset_id": asset["id"], "indicator": "MARKET_DECLINE"}, ACCT
    )
    validate_error(resp, ApiErrorId.ERR_IMPAIRMENT_REVIEW_OPEN, 409)


def test_review_window_frees_after_dismiss(api):
    """PRD §3.4: "At most one review per asset may be `OPEN` at a time — a second
    open attempt is rejected with `ERR_IMPAIRMENT_REVIEW_OPEN`."
    PRD §3.4: "Dismissing moves the review from `OPEN` to the terminal status
    `DISMISSED` with no financial effect; it is the correct outcome when the
    carrying amount is fully recoverable."
    PRD §3.4: "Reviews can be listed and filtered by `asset_id` or `status`."

    Design: Difficulty/resource_temporal_overlap/impairment_review_open_window_exclusivity
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-960", description="Reviewed asset",
        acquisition_cost_cents=400000,
    )
    first = create_open_review(asset["id"], indicator="OBSOLESCENCE")

    blocked = api.create_impairment_review(
        {"asset_id": asset["id"], "indicator": "MARKET_DECLINE"}, ACCT
    )
    validate_error(blocked, ApiErrorId.ERR_IMPAIRMENT_REVIEW_OPEN, 409)

    dismissed = validate_success(
        api.dismiss_impairment_review(first["id"], CTRL), 200
    )
    assert dismissed["status"] == "DISMISSED"

    third = validate_success(
        api.create_impairment_review(
            {"asset_id": asset["id"], "indicator": "MARKET_DECLINE"}, ACCT
        ),
        201,
    )
    assert third["status"] == "OPEN"

    reviews, meta = validate_paginated(
        api.list_impairment_reviews(ACCT, params={"asset_id": asset["id"]})
    )
    assert meta["total_count"] == 2, "the dismissed review plus the new OPEN one"
    assert sorted(r["status"] for r in reviews) == ["DISMISSED", "OPEN"]


def test_impairment_confirm_without_writedown_returns_error(api):
    """PRD §3.4: "The write-down is computed as `net_book_value_cents` minus
    `recoverable_value_cents`; if that difference is zero or negative, there is
    nothing to write down, the confirm is rejected with
    `ERR_NO_IMPAIRMENT_INDICATED` (HTTP 422), and the review should be dismissed
    instead."

    Design: Corner/calculations/impairment_confirm_without_writedown_returns_error
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-030", description="No impairment",
        acquisition_cost_cents=120000, useful_life_months=12,
    )
    create_and_post_run("2026-01")
    version = current_asset_version(asset["id"])
    review = create_open_review(asset["id"], indicator="OBSOLESCENCE")

    resp = api.confirm_impairment_review(
        review["id"],
        {"recoverable_value_cents": 110000, "expected_asset_version": version},
        CTRL,
    )
    validate_error(resp, ApiErrorId.ERR_NO_IMPAIRMENT_INDICATED, 422)

    still_open = validate_success(
        api.get_impairment_review(review["id"], ACCT), 200
    )
    assert still_open["status"] == "OPEN", "failed confirm leaves the review OPEN"

    dismissed = validate_success(
        api.dismiss_impairment_review(review["id"], CTRL), 200
    )
    assert dismissed["status"] == "DISMISSED"
    assert refresh_asset(asset["id"])["impairment_total_cents"] == 0


def test_confirm_on_terminal_review_returns_invalid_state(api):
    """PRD §3.4: "Confirming or dismissing a review that is no longer `OPEN` is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/validations/confirm_on_terminal_review_returns_invalid_state
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-057", description="Terminal review",
        acquisition_cost_cents=120000, useful_life_months=12,
    )
    create_and_post_run("2026-01")
    review = create_open_review(asset["id"], indicator="DAMAGE")
    confirmed = validate_success(
        api.confirm_impairment_review(
            review["id"],
            {"recoverable_value_cents": 50000,
             "expected_asset_version": current_asset_version(asset["id"])},
            CTRL,
        ),
        200,
    )
    assert confirmed["status"] == "WRITTEN_DOWN"
    assert confirmed["write_down_cents"] == 60000

    resp = api.confirm_impairment_review(
        review["id"],
        {"recoverable_value_cents": 40000,
         "expected_asset_version": current_asset_version(asset["id"])},
        CTRL,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert refresh_asset(asset["id"])["impairment_total_cents"] == 60000, (
        "the second confirm applied nothing"
    )


def test_impairment_confirm_stale_asset_occ(api):
    """PRD §2.6: "The confirm request must carry `expected_asset_version` equal
    to the `version` of the reviewed asset at the time the recoverable-value
    estimate was computed. If the asset's version has advanced since that
    observation — for example because a depreciation run has posted additional
    accumulated depreciation and changed the net book value — the confirm is
    rejected with `ERR_STALE_VERSION` (HTTP 412), because the write-down would be
    based on a stale carrying amount."

    Design: Corner/complexity_layers/impairment_confirm_stale_asset_occ
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-081", description="OCC review asset",
        acquisition_cost_cents=120000, useful_life_months=12,
    )
    review = create_open_review(asset["id"], indicator="MARKET_DECLINE")
    stale_version = current_asset_version(asset["id"])

    create_and_post_run("2026-01")  # bumps the asset version, NBV now 110000

    stale = api.confirm_impairment_review(
        review["id"],
        {"recoverable_value_cents": 0, "expected_asset_version": stale_version},
        CTRL,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

    still_open = validate_success(
        api.get_impairment_review(review["id"], ACCT), 200
    )
    assert still_open["status"] == "OPEN"
    assert refresh_asset(asset["id"])["impairment_total_cents"] == 0

    confirmed = validate_success(
        api.confirm_impairment_review(
            review["id"],
            {"recoverable_value_cents": 0,
             "expected_asset_version": current_asset_version(asset["id"])},
            CTRL,
        ),
        200,
    )
    assert confirmed["status"] == "WRITTEN_DOWN"
    assert confirmed["write_down_cents"] == 110000, (
        "recomputed against the post-run net book value"
    )
