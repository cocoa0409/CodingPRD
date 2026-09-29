"""Writes that are gated by the state of a *different* row.

Neither of these requests is refused for anything in its own payload.  A mapping
create is refused because the chart it points at has not been standardized yet, and
a return close is diverted because the shopper who bought the goods has been
blocked; in both cases the identical request behaves differently once the other
entity moves.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ApiClient,
    ApiErrorId,
    chart_row,
    create_size_chart_mapping_payload,
    grade_rule,
    make_fit_analyst_headers,
    make_merch_ops_admin_headers,
    make_returns_auditor_headers,
    resolve_return_case_payload,
    size_label_pair,
    size_point,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx  # noqa: E402

CLEAN_FIVE_SIZE_POINTS = [
    size_point("XS", 0, 800, 720, 840, 700),
    size_point("S", 1, 840, 760, 880, 710),
    size_point("M", 2, 880, 800, 920, 720),
    size_point("L", 3, 925, 845, 965, 730),
    size_point("XL", 4, 965, 885, 1005, 740),
]

CHEST_GRADE_RULES = [grade_rule("CHEST", 40, 1250, 3)]

FIVE_ROW_TOPS_CHART = [
    chart_row("XS", 0, 780, 819, 700, 739, "XS", "0", "32", "4"),
    chart_row("S", 1, 820, 859, 740, 779, "S", "2", "34", "6"),
    chart_row("M", 2, 860, 899, 780, 819, "M", "4", "36", "8"),
    chart_row("L", 3, 900, 944, 820, 864, "L", "6", "38", "10"),
    chart_row("XL", 4, 945, 984, 865, 904, "XL", "8", "40", "12"),
]

FOUR_OF_FIVE_PAIRS = [
    size_label_pair("S", "S"),
    size_label_pair("M", "M"),
    size_label_pair("L", "L"),
    size_label_pair("XL", "XL"),
]


def _build_verified_item_and_draft_chart(api: ApiClient) -> dict:
    """A listed item whose specification is verified, paired with a chart that has
    been drafted and deliberately left unstandardized."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    vendor = fx.create_vendor(
        api, name="Draftchart Denim", brand_code="DRFT", correction_budget_cents=10000
    )
    item = fx.list_item(
        api,
        fx.create_item(
            api,
            vendor["id"],
            sku="DRFT-TEE-01",
            category_code="TOPS",
            brand_size_system="US_ALPHA",
            unit_price_cents=2295,
        )["id"],
    )
    spec = fx.create_spec(
        api,
        item["id"],
        vendor["id"],
        size_system="US_ALPHA",
        base_size_label="M",
        fabric_stretch_class="RIGID",
        size_points=CLEAN_FIVE_SIZE_POINTS,
        grade_rules=CHEST_GRADE_RULES,
    )
    fx.submit_spec(api, spec["id"], vendor["id"])
    fx.verify_spec(api, spec["id"])
    chart = fx.create_chart(
        api,
        chart_code="STD-TOPS-DR",
        size_system="US_ALPHA",
        category_code="TOPS",
        rows=FIVE_ROW_TOPS_CHART,
    )
    return {
        "vendor": vendor,
        "item": fx.read_item(api, item["id"]),
        "spec": spec,
        "chart": chart,
    }


def _mapping_payload(built: dict) -> dict:
    """The four-pair mapping request, pinned to the item version the analyst read
    before the chart moved anywhere, so the identical body can be replayed."""
    return create_size_chart_mapping_payload(
        built["item"]["id"],
        built["chart"]["id"],
        built["item"]["version"],
        size_label_pairs=FOUR_OF_FIVE_PAIRS,
    )


def test_a_chart_still_in_draft_cannot_be_mapped_onto(api):
    """PRD §2.9: "The referenced size chart has `status` `STANDARDIZED` and its
    `category_code` equals the item's `category_code`, otherwise
    `ERR_CHART_NOT_STANDARDIZED` (409)."  Nothing in the mapping request is wrong —
    the item is listed, its specification is verified and every label pairs — yet the
    chart's own status refuses the write with HTTP 409.

    Design: Difficulty/cross_entity_state_dependency/mapping_creation_requires_standardized_chart
    """
    built = _build_verified_item_and_draft_chart(api)

    assert built["chart"]["status"] == "DRAFT"

    response = api.create_size_chart_mapping(
        _mapping_payload(built), make_fit_analyst_headers()
    )
    validate_error(response, ApiErrorId.ERR_CHART_NOT_STANDARDIZED.value, 409)


def test_the_refused_mapping_leaves_the_item_row_exactly_as_it_was(api):
    """PRD §2.4: "`version` (integer): a counter that starts at 1 on creation and
    increases by exactly 1 on every mutation of that row."  A refused mapping mutates
    nothing, so the item's version stands still, its readiness axis is still
    unverified, and the item owns no mapping rows at all.

    Design: Difficulty/cross_entity_state_dependency/mapping_creation_requires_standardized_chart
    """
    built = _build_verified_item_and_draft_chart(api)
    version_before = built["item"]["version"]

    api.create_size_chart_mapping(_mapping_payload(built), make_fit_analyst_headers())

    item = fx.read_item(api, built["item"]["id"])
    assert item["version"] == version_before
    assert item["fit_readiness"] == "UNVERIFIED"

    rows, _ = validate_paginated(
        api.list_size_chart_mappings(
            make_merch_ops_admin_headers(), {"item_id": built["item"]["id"]}
        )
    )
    assert rows == []


def test_standardizing_the_chart_refreshes_its_row_count_and_median_anchor(api):
    """PRD §3.3: "On success, `row_count` and `median_row_index` are refreshed from
    the stored rows."  The gate that unblocks the mapping is a transition on the chart
    itself: five rows leave `row_count` at 5 and the median anchor at index 2, which is
    the row count less 1 halved with the fraction discarded.

    Design: Difficulty/cross_entity_state_dependency/mapping_creation_requires_standardized_chart
    """
    built = _build_verified_item_and_draft_chart(api)

    chart = fx.standardize_chart(api, built["chart"]["id"])

    assert chart["status"] == "STANDARDIZED"
    assert chart["row_count"] == 5
    assert chart["median_row_index"] == 2


def test_the_identical_payload_is_accepted_once_the_chart_is_standardized(api):
    """PRD §3.3: "The item's readiness axis then reacts: an item at `UNVERIFIED`
    advances to `CHART_MAPPED`; an item already at `CHART_MAPPED` stays at
    `CHART_MAPPED`, the further mapping being accepted and merely superseding the prior
    one; and an item that had reached `GUIDANCE_READY` falls back to `CHART_MAPPED`, so
    fit guidance stops being servable until it is published again."  The replayed body
    is byte-for-byte the one that was refused, including the item version it was
    pinned to, so the only thing that changed is the chart's status.

    Design: Difficulty/cross_entity_state_dependency/mapping_creation_requires_standardized_chart
    """
    built = _build_verified_item_and_draft_chart(api)
    payload = _mapping_payload(built)
    api.create_size_chart_mapping(payload, make_fit_analyst_headers())

    fx.standardize_chart(api, built["chart"]["id"])
    mapping = validate_success(
        api.create_size_chart_mapping(payload, make_fit_analyst_headers()),
        201,
    )

    assert mapping["status"] == "ACTIVE"
    assert mapping["coverage_bp"] == 8000

    item = fx.read_item(api, built["item"]["id"])
    assert item["fit_readiness"] == "CHART_MAPPED"


def _build_blocked_purchaser_with_a_coded_fit_case(api: ApiClient) -> dict:
    """A shopper with four delivered lines and three live cases, which blocks them on
    the rate rule, whose first case has already been coded into the fit branch and so
    is waiting to be closed."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    vendor = fx.create_vendor(
        api, name="Denied Drapery", brand_code="DNYD", correction_budget_cents=10000
    )
    item = fx.list_item(
        api,
        fx.create_item(
            api,
            vendor["id"],
            sku="DNYD-TEE-01",
            category_code="TOPS",
            brand_size_system="US_ALPHA",
            unit_price_cents=2295,
        )["id"],
    )
    fx.create_policy(
        api,
        category_code="TOPS",
        window_days=30,
        restocking_applies=True,
        non_refundable_shipping=False,
        effective_from="2026-01-01T00:00:00Z",
    )
    customer = fx.create_customer(api, email="shopper-r7b@example.com")
    lines = [
        fx.create_order_line(
            api,
            customer["id"],
            item["id"],
            size_label=label,
            quantity=1,
            unit_price_cents=2295,
            shipping_allocated_cents=0,
            delivered_at="2026-05-20T00:00:00Z",
        )
        for label in ("M", "M", "M", "L")
    ]

    first = fx.open_case(
        api, lines[0]["id"], customer["id"], requested_reason_code="FIT_TOO_SMALL"
    )
    for order_line in lines[1:3]:
        fx.open_case(
            api, order_line["id"], customer["id"], requested_reason_code="CHANGE_OF_MIND"
        )

    return {
        "item": item,
        "customer": fx.read_customer(api, customer["id"]),
        "order_lines": lines,
        "case": fx.classify_case(api, first["id"], "FIT_TOO_SMALL"),
    }


def test_the_purchasers_standing_and_not_the_auditor_decides_where_the_close_lands(api):
    """PRD §3.8: "Where the case lands is decided by the purchaser's standing rather
    than by the auditor: a purchaser whose `abuse_status` is not `BLOCKED` yields
    `RESOLVED_REFUNDED`, and a purchaser whose `abuse_status` is `BLOCKED` yields
    `RESOLVED_DENIED`."  The auditor submits an ordinary grade-A close on a case sitting
    in the fit branch; the shopper's blocked standing diverts it to the denied landing,
    and both operators are still stamped on the row.

    Design: Difficulty/cross_entity_state_dependency/resolve_denies_refund_when_purchaser_blocked
    """
    built = _build_blocked_purchaser_with_a_coded_fit_case(api)

    assert built["customer"]["return_rate_bp"] == 7500
    assert built["customer"]["abuse_status"] == "BLOCKED"
    assert built["case"]["status"] == "FIT_REVIEW"

    case = validate_success(
        api.resolve_return_case(
            built["case"]["id"],
            resolve_return_case_payload("RESELLABLE_A"),
            make_returns_auditor_headers("auditor-2"),
        )
    )

    assert case["status"] == "RESOLVED_DENIED"
    assert case["classified_by_user_id"] == "auditor-1"
    assert case["resolved_by_user_id"] == "auditor-2"


def test_the_denied_landing_pays_nothing_and_withholds_nothing(api):
    """PRD §3.8: "A case landing on `RESOLVED_DENIED` short-circuits the whole
    computation: both `restocking_fee_cents` and `refund_amount_cents` are 0."  There
    is no money to divide, so the fee arithmetic is never reached and the shopper's
    lifetime refunded total never moves off zero.

    Design: Difficulty/cross_entity_state_dependency/resolve_denies_refund_when_purchaser_blocked
    """
    built = _build_blocked_purchaser_with_a_coded_fit_case(api)

    case = fx.resolve_case(api, built["case"]["id"], "RESELLABLE_A")

    assert case["restocking_fee_cents"] == 0
    assert case["refund_amount_cents"] == 0

    customer = fx.read_customer(api, built["customer"]["id"])
    assert customer["refunded_total_cents"] == 0


def test_a_denied_close_posts_only_the_two_unavoidable_components(api):
    """PRD §3.8: "A case landing on `RESOLVED_DENIED` writes only two postings —
    `FREIGHT_INBOUND` and `PROCESSING_LABOR`."  Grade A would ordinarily have drawn a
    refurb charge and the refund a payment fee; the denied landing writes neither, so
    the ledger carries 795 cents of inbound freight and nine minutes of fit handling
    at 62 cents a minute and nothing else.

    Design: Difficulty/cross_entity_state_dependency/resolve_denies_refund_when_purchaser_blocked
    """
    built = _build_blocked_purchaser_with_a_coded_fit_case(api)

    case = fx.resolve_case(api, built["case"]["id"], "RESELLABLE_A")
    assert case["total_cost_cents"] == 1353

    postings = fx.read_cost_postings(api, built["case"]["id"])
    assert len(postings) == 2
    assert [row["component"] for row in postings] == [
        "FREIGHT_INBOUND",
        "PROCESSING_LABOR",
    ]
    assert [row["amount_cents"] for row in postings] == [795, 558]

    item = fx.read_item(api, built["item"]["id"])
    assert item["return_cost_accrued_cents"] == 1353


def test_the_shopper_keeps_the_goods_the_denied_case_covered(api):
    """PRD §3.8: "Any of the four review branches closing on `RESOLVED_DENIED` writes
    `refund_amount_cents` 0 and `restocking_fee_cents` 0, writes only the
    `FREIGHT_INBOUND` and `PROCESSING_LABOR` postings, and moves the order line to
    `KEPT` rather than `RETURNED` — the shopper keeps the goods and is paid nothing."
    The line under the denied case therefore ends on a different terminal status than
    the lines under the shopper's two still-open cases.

    Design: Difficulty/cross_entity_state_dependency/resolve_denies_refund_when_purchaser_blocked
    """
    built = _build_blocked_purchaser_with_a_coded_fit_case(api)

    fx.resolve_case(api, built["case"]["id"], "RESELLABLE_A")

    closed_line = fx.read_order_line(api, built["order_lines"][0]["id"])
    assert closed_line["status"] == "KEPT"

    open_line = fx.read_order_line(api, built["order_lines"][1]["id"])
    assert open_line["status"] == "RETURN_IN_PROGRESS"


def test_a_denied_fit_case_still_counts_against_the_item(api):
    """PRD §3.8: "The item counters for the case's `reason_family` still advance,
    because a denied case is a closed case: a denied fit case still raises
    `fit_return_count` and `total_return_count`, and a denied expectation case still
    raises `expectation_return_count` and `total_return_count` and still sets
    `pdp_review_required`."  One denied fit return over four delivered units scores
    1,875 basis points, which is enough to put the item on watch even though the
    shopper was paid nothing.

    Design: Difficulty/cross_entity_state_dependency/resolve_denies_refund_when_purchaser_blocked
    """
    built = _build_blocked_purchaser_with_a_coded_fit_case(api)

    fx.resolve_case(api, built["case"]["id"], "RESELLABLE_A")

    item = fx.read_item(api, built["item"]["id"])
    assert item["fit_return_count"] == 1
    assert item["total_return_count"] == 1
    assert item["fit_return_rate_bp"] == 2500
    assert item["chronic_return_score_bp"] == 1875
    assert item["fit_watch_state"] == "WATCH"
