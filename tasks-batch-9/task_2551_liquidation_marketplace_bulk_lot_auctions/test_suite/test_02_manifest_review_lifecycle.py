"""The lot lifecycle: submission, review, the rejection revision loop, and the
existence gates that guard lot-scoped writes."""

from test_helpers import (
    REVIEWER,
    REVIEWER_USER_ID,
    SECOND_REVIEWER_USER_ID,
    bootstrap_marketplace,
    create_lot_with_lines,
    create_seller,
    lot_payload,
    make_marketplace_ops_headers,
    make_seller_ops_headers,
    manifest_line_payload,
    manifest_review_payload,
    read_lot,
    setup_approved_lot,
    submit_manifest,
    total_count,
    validate_error,
    validate_paginated,
    validate_success,
)

ONE_LINE = [
    {"sku": "APP-RET-0001", "unit_count": 100, "unit_retail_cents": 40_000,
     "declared_condition": "USED_GOOD"},
]
SECOND_LINE = {
    "sku": "APP-200",
    "unit_count": 300,
    "unit_retail_cents": 20_000,
    "declared_condition": "USED_GOOD",
}

UNKNOWN_LOT_ID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_PARENT_LOT_ID = "22222222-2222-4222-8222-222222222222"
UNKNOWN_WAREHOUSE_ID = "33333333-3333-4333-8333-333333333333"


def test_lot_starts_in_draft_and_reaches_manifest_in_review_on_submission(api):
    """PRD 3.1: "Submitting a manifest advances the lot `DRAFT →
    MANIFEST_IN_REVIEW`. The submission takes no payload; the lot must be in
    `DRAFT`, the caller's `X-User-ID` must equal the lot's `seller_id`, and the
    lot must hold at least one line with `line_status` equal to `ACTIVE`."

    Design: Corner/state_machines/lot_starts_in_draft_and_reaches_manifest_in_review_on_submission
    """
    env = bootstrap_marketplace()
    built = create_lot_with_lines(env, ONE_LINE)
    lot_id = built["lot"]["id"]
    assert built["lot"]["lot_status"] == "DRAFT"

    validate_success(api.submit_manifest(lot_id, {}, env["seller_headers"]))

    lot = read_lot(env, lot_id)
    assert lot["lot_status"] == "MANIFEST_IN_REVIEW"
    assert lot["manifest_reviewed_by_user_id"] is None
    assert lot["manifest_accuracy_score"] is None
    assert lot["declared_unit_count"] == 100
    assert lot["declared_retail_value_cents"] == 4_000_000


def test_second_manifest_review_on_an_approved_lot_is_rejected(api):
    """PRD 3.1: "From `MANIFEST_IN_REVIEW`, an approval advances the lot to
    `MANIFEST_APPROVED` and a rejection advances it to `MANIFEST_REJECTED`;
    either way the reviewing operator's `X-User-ID` is written to
    `manifest_reviewed_by_user_id` and the lot's `version` advances by one."
    PRD 2.5: "The entity being written is in a state from which the requested
    transition is legal: `ERR_LOT_STATE_INVALID` (409), `ERR_LISTING_STATE_INVALID`
    (409), `ERR_NEGOTIATION_STATE_INVALID` or `ERR_NOT_YOUR_TURN` (409),
    `ERR_ORDER_PAYMENT_STATE_INVALID` (409), `ERR_ORDER_LOGISTICS_STATE_INVALID`
    (409), `ERR_APPOINTMENT_STATE_INVALID` (409), `ERR_CLAIM_STATE_INVALID` (409)
    or `ERR_BUYER_QUALIFICATION_STATE_INVALID` (409), according to the entity in
    question."

    Design: Corner/state_machines/second_manifest_review_on_approved_lot_is_rejected
    """
    env = bootstrap_marketplace()
    built = setup_approved_lot(env, ONE_LINE)
    lot_id = built["lot"]["id"]
    assert built["lot"]["lot_status"] == "MANIFEST_APPROVED"
    assert built["lot"]["manifest_reviewed_by_user_id"] == REVIEWER_USER_ID

    validate_error(
        api.review_manifest(
            lot_id,
            manifest_review_payload("APPROVE", review_note="duplicate review"),
            make_marketplace_ops_headers(SECOND_REVIEWER_USER_ID),
        ),
        "ERR_LOT_STATE_INVALID",
        409,
    )

    lot = read_lot(env, lot_id)
    assert lot["lot_status"] == "MANIFEST_APPROVED"
    assert lot["manifest_reviewed_by_user_id"] == REVIEWER_USER_ID


def test_manifest_rejection_cycles_the_lot_back_to_draft_and_into_review_again(api):
    """PRD 3.1: "Both appending and voiding are only legal while the lot's
    `lot_status` is `DRAFT` or `MANIFEST_REJECTED`; any other state is
    `ERR_LOT_STATE_INVALID`. When the lot was in `MANIFEST_REJECTED`, either edit
    returns it to `DRAFT` — the `MANIFEST_REJECTED → DRAFT` revision loop — which
    forces a fresh submission rather than allowing a quietly amended manifest to
    inherit an old review."

    Design: Corner/state_machines/manifest_rejection_cycles_the_lot_back_to_draft_and_into_review_again
    """
    env = bootstrap_marketplace()
    built = create_lot_with_lines(env, ONE_LINE)
    lot_id = built["lot"]["id"]
    submit_manifest(env, lot_id)
    validate_success(
        api.review_manifest(
            lot_id, manifest_review_payload("REJECT", review_note="counts do not match"),
            REVIEWER,
        )
    )
    assert read_lot(env, lot_id)["lot_status"] == "MANIFEST_REJECTED"

    validate_success(
        api.create_manifest_line(
            lot_id, manifest_line_payload(**SECOND_LINE), env["seller_headers"]
        ),
        201,
    )
    revised = read_lot(env, lot_id)
    assert revised["lot_status"] == "DRAFT"
    assert revised["manifest_line_count"] == 2
    assert revised["declared_unit_count"] == 400
    assert revised["declared_retail_value_cents"] == 10_000_000

    validate_success(api.submit_manifest(lot_id, {}, env["seller_headers"]))
    assert read_lot(env, lot_id)["lot_status"] == "MANIFEST_IN_REVIEW"

    validate_success(
        api.review_manifest(
            lot_id,
            manifest_review_payload("APPROVE", review_note="second pass matches"),
            REVIEWER,
        )
    )
    approved = read_lot(env, lot_id)
    assert approved["lot_status"] == "MANIFEST_APPROVED"
    assert approved["manifest_reviewed_by_user_id"] == REVIEWER_USER_ID


def test_lot_get_with_an_unknown_id_returns_lot_not_found(api):
    """PRD 2.5: "Every identifier embedded in the URL path resolves to a stored
    row, checked from left to right, with the leftmost unresolved segment
    deciding the error: `ERR_LOT_NOT_FOUND`, `ERR_MANIFEST_LINE_NOT_FOUND`,
    `ERR_LISTING_NOT_FOUND`, `ERR_NEGOTIATION_NOT_FOUND`,
    `ERR_SALE_ORDER_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`,
    `ERR_CLAIM_NOT_FOUND`, `ERR_BUYER_NOT_FOUND` or `ERR_SELLER_NOT_FOUND`, each
    HTTP 404."

    Design: Corner/entities/lot_get_with_unknown_id_returns_lot_not_found
    """
    validate_error(api.get_lot(UNKNOWN_LOT_ID, REVIEWER), "ERR_LOT_NOT_FOUND", 404)


def test_manifest_line_creation_under_an_unknown_lot_returns_lot_not_found(api):
    """PRD 2.9: "Path parameters are resolved strictly left to right, and the
    first segment that fails to resolve determines the 404 error returned — a
    request naming a nonexistent lot and a nonexistent manifest line reports the
    lot as missing, because the lot segment appears first. Only after every path
    segment resolves does the platform consider ownership, body references,
    shape, concurrency or state."

    Design: Corner/entities/manifest_line_creation_under_unknown_lot_returns_lot_not_found
    """
    seller = create_seller()
    seller_headers = make_seller_ops_headers(seller["id"])

    validate_error(
        api.create_manifest_line(
            UNKNOWN_PARENT_LOT_ID,
            manifest_line_payload(sku="APP-100", unit_count=100, unit_retail_cents=40_000),
            seller_headers,
        ),
        "ERR_LOT_NOT_FOUND",
        404,
    )

    listed = api.list_manifest_lines(REVIEWER)
    validate_paginated(listed)
    assert total_count(listed) == 0


def test_lot_creation_with_an_unknown_warehouse_id_is_rejected(api):
    """PRD 2.5: "Every foreign reference carried in the request body resolves to
    a stored row — `seller_id`, `warehouse_id`, `brand_policy_id`, `lot_id`,
    `listing_id`, `buyer_id`, `carrier_id` and `manifest_line_id` — reported as
    `ERR_SELLER_NOT_FOUND`, `ERR_WAREHOUSE_NOT_FOUND`,
    `ERR_BRAND_POLICY_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
    `ERR_BUYER_NOT_FOUND`, `ERR_CARRIER_NOT_FOUND` or
    `ERR_MANIFEST_LINE_NOT_FOUND` respectively, each HTTP 404."

    Design: Corner/entities/lot_creation_with_unknown_warehouse_id_is_rejected
    """
    seller = create_seller()
    seller_headers = make_seller_ops_headers(seller["id"])

    validate_error(
        api.create_lot(
            lot_payload(seller["id"], UNKNOWN_WAREHOUSE_ID,
                        title="Apparel customer returns S1"),
            seller_headers,
        ),
        "ERR_WAREHOUSE_NOT_FOUND",
        404,
    )

    listed = api.list_lots(REVIEWER, params={"seller_id": seller["id"]})
    validate_paginated(listed)
    assert total_count(listed) == 0


def test_manifest_line_creation_missing_unit_count_is_rejected(api):
    """PRD 2.5: "All required input fields present; every enum-valued field
    inside its declared value set; every integer inside its declared range
    (`unit_count` at least 1, `unit_retail_cents` at least 1, `dock_door_count`
    at least 1, `daily_pickup_capacity` at least 1, `bid_increment_cents` at
    least 1); `window_end_at` strictly later than `window_start_at`; and the
    format-conditional price field present for the chosen sale mechanism
    (`opening_bid_cents` for an auction, `ask_price_cents` for a fixed price,
    `min_offer_cents` for negotiated terms). Violation is `ERR_INVALID_REQUEST`
    (400)."

    Design: Corner/entities/manifest_line_creation_missing_unit_count_is_rejected
    """
    env = bootstrap_marketplace()
    built = create_lot_with_lines(env, [])
    lot_id = built["lot"]["id"]

    validate_error(
        api.create_manifest_line(
            lot_id,
            {"sku": "APP-100", "unit_retail_cents": 40_000,
             "declared_condition": "USED_GOOD"},
            env["seller_headers"],
        ),
        "ERR_INVALID_REQUEST",
        400,
    )

    lot = read_lot(env, lot_id)
    assert lot["manifest_line_count"] == 0
    assert lot["declared_unit_count"] == 0
    assert lot["declared_retail_value_cents"] == 0

    listed = api.list_lot_manifest_lines(lot_id, env["seller_headers"])
    validate_paginated(listed)
    assert total_count(listed) == 0
