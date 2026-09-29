"""Lot manifests: aggregate recomputation, voids and the empty-manifest boundary."""

from test_helpers import (
    CANONICAL_LOT_LINES,
    bootstrap_marketplace,
    create_lot_with_lines,
    manifest_line_payload,
    read_lot,
    read_manifest_line,
    total_count,
    validate_error,
    validate_paginated,
    validate_success,
)

ADDED_LINE = {
    "sku": "APP-RET-0003",
    "unit_count": 60,
    "unit_retail_cents": 15_000,
    "declared_condition": "USED_GOOD",
}

SINGLE_LINE = [
    {"sku": "APP-RET-0009", "unit_count": 40, "unit_retail_cents": 20_000,
     "declared_condition": "USED_GOOD"},
]

THREE_LINES = [
    {"sku": "APP-RET-0001", "unit_count": 100, "unit_retail_cents": 40_000,
     "declared_condition": "USED_GOOD"},
    {"sku": "APP-RET-0002", "unit_count": 300, "unit_retail_cents": 20_000,
     "declared_condition": "USED_GOOD"},
    {"sku": "APP-RET-0003", "unit_count": 50, "unit_retail_cents": 10_000,
     "declared_condition": "DAMAGED"},
]


def test_voiding_the_added_line_restores_the_declared_unit_total(api):
    """PRD 3.1: "Voiding a line is the seller's correction mechanism. A voided
    line has its `line_status` set to `VOIDED` and is retained permanently for
    audit, but it leaves every aggregate immediately: the three lot aggregates
    are recomputed over the remaining `ACTIVE` lines, which restores the
    declared unit total to exactly what it would have been had the voided line
    never been appended."

    Design: Difficulty/compensating_invariant/declared_unit_total_restored_by_voiding_the_added_line
    """
    env = bootstrap_marketplace()
    built = create_lot_with_lines(env, CANONICAL_LOT_LINES)
    lot_id = built["lot"]["id"]

    assert built["lot"]["manifest_line_count"] == 2
    assert built["lot"]["declared_unit_count"] == 400
    assert built["lot"]["declared_retail_value_cents"] == 10_000_000

    added = validate_success(
        api.create_manifest_line(
            lot_id, manifest_line_payload(**ADDED_LINE), env["seller_headers"]
        ),
        201,
    )
    grown = read_lot(env, lot_id)
    assert grown["manifest_line_count"] == 3
    assert grown["declared_unit_count"] == 460
    assert grown["declared_retail_value_cents"] == 10_900_000

    validate_success(
        api.void_manifest_line(added["id"], {}, env["seller_headers"])
    )
    restored = read_lot(env, lot_id)
    assert restored["manifest_line_count"] == 2
    assert restored["declared_unit_count"] == 400
    assert restored["declared_retail_value_cents"] == 10_000_000


def test_voided_line_is_retained_but_leaves_the_active_line_population(api):
    """PRD 3.1: "Voiding a line is the seller's correction mechanism. A voided
    line has its `line_status` set to `VOIDED` and is retained permanently for
    audit, but it leaves every aggregate immediately: the three lot aggregates
    are recomputed over the remaining `ACTIVE` lines, which restores the
    declared unit total to exactly what it would have been had the voided line
    never been appended."

    Design: Difficulty/compensating_invariant/declared_unit_total_restored_by_voiding_the_added_line
    """
    env = bootstrap_marketplace()
    built = create_lot_with_lines(env, CANONICAL_LOT_LINES)
    lot_id = built["lot"]["id"]

    added = validate_success(
        api.create_manifest_line(
            lot_id, manifest_line_payload(**ADDED_LINE), env["seller_headers"]
        ),
        201,
    )
    validate_success(api.void_manifest_line(added["id"], {}, env["seller_headers"]))

    voided = read_manifest_line(env, added["id"])
    assert voided["line_status"] == "VOIDED"
    assert voided["unit_count"] == 60
    assert voided["unit_retail_cents"] == 15_000

    unfiltered = api.list_lot_manifest_lines(lot_id, env["seller_headers"])
    validate_paginated(unfiltered)
    assert total_count(unfiltered) == 3

    active = api.list_lot_manifest_lines(
        lot_id, env["seller_headers"], params={"line_status": "ACTIVE"}
    )
    validate_paginated(active)
    assert total_count(active) == 2

    lot = read_lot(env, lot_id)
    assert lot["manifest_line_count"] == 2
    assert lot["declared_unit_count"] == 400
    assert lot["declared_retail_value_cents"] == 10_000_000


def test_manifest_submission_refused_when_the_last_active_line_is_voided(api):
    """PRD 3.1: "A submission on a lot with zero active lines — the zero-count
    boundary, which occurs naturally when a seller voids the last surviving
    line — is rejected with `ERR_MANIFEST_EMPTY`."

    Design: Difficulty/boundary_precision_check/manifest_submission_blocked_at_empty_active_line_boundary
    """
    env = bootstrap_marketplace()
    built = create_lot_with_lines(env, SINGLE_LINE)
    lot_id = built["lot"]["id"]
    line_id = built["lines"][0]["id"]

    assert built["lot"]["manifest_line_count"] == 1
    assert built["lot"]["declared_unit_count"] == 40
    assert built["lot"]["declared_retail_value_cents"] == 800_000

    validate_success(api.void_manifest_line(line_id, {}, env["seller_headers"]))

    validate_error(
        api.submit_manifest(lot_id, {}, env["seller_headers"]),
        "ERR_MANIFEST_EMPTY",
        422,
    )

    lot = read_lot(env, lot_id)
    assert lot["lot_status"] == "DRAFT"
    assert lot["manifest_line_count"] == 0
    assert lot["declared_unit_count"] == 0
    assert lot["declared_retail_value_cents"] == 0

    assert read_manifest_line(env, line_id)["line_status"] == "VOIDED"

    active = api.list_lot_manifest_lines(
        lot_id, env["seller_headers"], params={"line_status": "ACTIVE"}
    )
    validate_paginated(active)
    assert total_count(active) == 0

    unfiltered = api.list_lot_manifest_lines(lot_id, env["seller_headers"])
    assert total_count(unfiltered) == 1


def test_manifest_submission_accepted_at_exactly_one_active_line(api):
    """PRD 3.1: "Submitting a manifest advances the lot `DRAFT →
    MANIFEST_IN_REVIEW`. The submission takes no payload; the lot must be in
    `DRAFT`, the caller's `X-User-ID` must equal the lot's `seller_id`, and the
    lot must hold at least one line with `line_status` equal to `ACTIVE`."

    Design: Difficulty/boundary_precision_check/manifest_submission_blocked_at_empty_active_line_boundary
    """
    env = bootstrap_marketplace()
    built = create_lot_with_lines(env, SINGLE_LINE)
    lot_id = built["lot"]["id"]

    validate_success(api.submit_manifest(lot_id, {}, env["seller_headers"]))

    lot = read_lot(env, lot_id)
    assert lot["lot_status"] == "MANIFEST_IN_REVIEW"
    assert lot["manifest_line_count"] == 1
    assert lot["declared_unit_count"] == 40
    assert lot["declared_retail_value_cents"] == 800_000


def test_lot_aggregate_fields_are_computed_from_active_manifest_lines(api):
    """PRD 3.1: "Appending a line recomputes the three lot aggregates over
    `ACTIVE` lines only: `manifest_line_count` becomes the number of such lines,
    `declared_unit_count` becomes the sum of their `unit_count` values, and
    `declared_retail_value_cents` becomes the sum, over those same lines, of
    each line's `unit_count` multiplied by its `unit_retail_cents`."

    Design: Corner/entities/lot_aggregate_fields_are_computed_from_active_manifest_lines
    """
    env = bootstrap_marketplace()
    built = create_lot_with_lines(env, CANONICAL_LOT_LINES)
    lot_id = built["lot"]["id"]
    first_line, second_line = built["lines"]

    before = read_lot(env, lot_id)
    assert before["manifest_line_count"] == 2
    assert before["declared_unit_count"] == 400
    assert before["declared_retail_value_cents"] == 10_000_000

    validate_success(api.void_manifest_line(first_line["id"], {}, env["seller_headers"]))

    after = read_lot(env, lot_id)
    assert after["manifest_line_count"] == 1
    assert after["declared_unit_count"] == 300
    assert after["declared_retail_value_cents"] == 6_000_000

    assert read_manifest_line(env, first_line["id"])["line_status"] == "VOIDED"
    assert read_manifest_line(env, second_line["id"])["line_status"] == "ACTIVE"

    active = api.list_lot_manifest_lines(
        lot_id, env["seller_headers"], params={"line_status": "ACTIVE"}
    )
    validate_paginated(active)
    assert total_count(active) == 1


def test_manifest_lines_listing_paginates_with_total_count_and_has_more(api):
    """PRD 2.3: "For list responses, the `meta` object carries `limit`,
    `offset`, `total_count` and `has_more`, where `total_count` is the size of
    the filtered result set before the page window is applied and `has_more` is
    true when unreturned rows remain beyond the current page."

    Design: Corner/entities/manifest_lines_listing_paginates_with_total_count_and_has_more
    """
    env = bootstrap_marketplace()
    built = create_lot_with_lines(env, THREE_LINES)
    lot_id = built["lot"]["id"]

    first_rows, first_meta = validate_paginated(
        api.list_lot_manifest_lines(
            lot_id, env["seller_headers"], params={"limit": 2, "offset": 0}
        )
    )
    assert len(first_rows) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["has_more"] is True

    second_rows, second_meta = validate_paginated(
        api.list_lot_manifest_lines(
            lot_id, env["seller_headers"], params={"limit": 2, "offset": 2}
        )
    )
    assert len(second_rows) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2
    assert second_meta["has_more"] is False

    lot = read_lot(env, lot_id)
    assert lot["manifest_line_count"] == 3
    assert lot["declared_unit_count"] == 450
    assert lot["declared_retail_value_cents"] == 10_500_000


def test_lot_retrieval_by_id_returns_the_stored_lot(api):
    """PRD 3.1: "Creation places the lot in `DRAFT` with `manifest_line_count`,
    `declared_unit_count` and `declared_retail_value_cents` all at zero,
    `manifest_accuracy_score` still null because no claim has ever been resolved
    against it, and `manifest_reviewed_by_user_id` still null."
    PRD 3.1: "One value is copied rather than computed: the lot's
    `de_branding_required` mirrors the linked brand policy's own
    `de_branding_required` at the instant of creation, and it is false when no
    `brand_policy_id` was supplied."

    Design: Corner/entities/lot_retrieval_by_id_returns_the_stored_lot
    """
    env = bootstrap_marketplace()
    built = create_lot_with_lines(env, [])
    lot_id = built["lot"]["id"]

    lot = validate_success(api.get_lot(lot_id, env["seller_headers"]))
    assert lot["seller_id"] == env["seller"]["id"]
    assert lot["warehouse_id"] == env["warehouse"]["id"]
    assert lot["category_code"] == "APPAREL"
    assert lot["condition_grade"] == "CUSTOMER_RETURNS"
    assert lot["lot_status"] == "DRAFT"
    assert lot["manifest_line_count"] == 0
    assert lot["declared_unit_count"] == 0
    assert lot["declared_retail_value_cents"] == 0
    assert lot["brand_policy_id"] is None
    assert lot["de_branding_required"] is False
    assert lot["manifest_accuracy_score"] is None
    assert lot["manifest_reviewed_by_user_id"] is None
