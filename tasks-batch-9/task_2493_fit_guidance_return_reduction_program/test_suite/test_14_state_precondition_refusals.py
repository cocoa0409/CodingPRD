"""Refusals that depend on the condition of rows the request only points at.

Nothing is wrong with any of these request bodies.  What blocks them lives
elsewhere: a policy table that covers a different category, a delivery date one day
too old, a brand that has run its reliability down, a size label the specification
never declared, chart rows that overlap, a product page that was never completed,
and an item that was never put on the storefront.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ApiClient,
    ApiErrorId,
    VIOLATING_TWO_POINT_RUN,
    chart_row,
    create_intervention_deployment_payload,
    create_return_case_payload,
    create_size_chart_mapping_payload,
    is_iso8601_timestamp,
    make_customer_headers,
    make_fit_analyst_headers,
    make_merch_ops_admin_headers,
    make_vendor_user_headers,
    size_label_pair,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx  # noqa: E402

SCENARIO_START = "2026-06-01T00:00:00Z"

TOPS_THIRTY_DAY_POLICY = {
    "window_days": 30,
    "restocking_applies": True,
    "non_refundable_shipping": False,
    "effective_from": "2026-01-01T00:00:00Z",
}

# Two rows whose body-chest ranges run backwards into each other: the second row
# starts at 800 while the first still claims everything up to 869.
OVERLAPPING_CHEST_ROWS = [
    chart_row("S", 0, 820, 869, 740, 779, "S", "2", "34", "6"),
    chart_row("M", 1, 800, 859, 780, 819, "M", "4", "36", "8"),
]


def test_a_return_on_a_category_no_policy_covers_is_refused(api):
    """PRD §2.9: "**Policy available.** Policy resolution finds at least one candidate
    row, otherwise `ERR_NO_RETURN_POLICY` (422). Applies to return-case creation."  The
    only policy row on file governs bottoms, and a policy authored for another category
    is not a candidate for a tops purchase, so the shopper has nothing to return
    against: no case row is written and the purchased line stays delivered.

    Design: Corner/validations/case_creation_without_a_covering_policy_returns_no_return_policy
    """
    built = fx.setup_listed_item(api, SCENARIO_START)
    bottoms_policy = fx.create_policy(
        api, category_code="BOTTOMS", **TOPS_THIRTY_DAY_POLICY
    )
    customer = fx.create_customer(api, email="shopper-v5@example.com")
    line = fx.create_order_line(
        api,
        customer["id"],
        built["item"]["id"],
        size_label="M",
        quantity=1,
        unit_price_cents=2295,
        shipping_allocated_cents=0,
        delivered_at="2026-05-20T00:00:00Z",
    )

    response = api.create_return_case(
        create_return_case_payload(line["id"], requested_reason_code="FIT_TOO_SMALL"),
        make_customer_headers(customer["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NO_RETURN_POLICY.value, 422)

    assert bottoms_policy["category_code"] == "BOTTOMS"

    _, meta = validate_paginated(
        api.list_return_cases(
            make_merch_ops_admin_headers(),
            {"order_line_id": line["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 0

    assert fx.read_order_line(api, line["id"])["status"] == "DELIVERED"
    assert fx.read_customer(api, customer["id"])["return_case_count"] == 0


def _build_two_lines_astride_the_deadline(api: ApiClient) -> dict:
    """Two otherwise identical purchases delivered one day apart under a thirty-day
    window, so at the current clock one is exactly on its deadline and the other is
    exactly one day past it."""
    built = fx.setup_listed_item(api, SCENARIO_START)
    built["policy"] = fx.create_policy(
        api, category_code="TOPS", **TOPS_THIRTY_DAY_POLICY
    )
    built["customer"] = fx.create_customer(api, email="shopper-v12@example.com")
    line_kwargs = {
        "size_label": "M",
        "quantity": 1,
        "unit_price_cents": 2295,
        "shipping_allocated_cents": 0,
    }
    built["line_on_the_deadline"] = fx.create_order_line(
        api,
        built["customer"]["id"],
        built["item"]["id"],
        delivered_at="2026-05-02T00:00:00Z",
        **line_kwargs,
    )
    built["line_one_day_past"] = fx.create_order_line(
        api,
        built["customer"]["id"],
        built["item"]["id"],
        delivered_at="2026-05-01T00:00:00Z",
        **line_kwargs,
    )
    return built


def test_a_request_landing_exactly_on_the_deadline_is_still_in_time(api):
    """PRD §3.7: "The request is accepted only when the logical clock is at or before
    `return_deadline_at` — the comparison is inclusive, so a request landing exactly on
    the deadline is in time — and a later clock is refused with
    `ERR_RETURN_WINDOW_CLOSED` and HTTP 422."  A line delivered on the second of May
    under a thirty-day window has its deadline at the very instant the clock now reads,
    so the return opens and takes the purchased line with it.

    Design: Corner/validations/return_window_deadline_boundary_accepts_and_expired_line_rejects
    """
    built = _build_two_lines_astride_the_deadline(api)

    case = validate_success(
        api.create_return_case(
            create_return_case_payload(
                built["line_on_the_deadline"]["id"],
                requested_reason_code="FIT_TOO_SMALL",
            ),
            make_customer_headers(built["customer"]["id"]),
        ),
        201,
    )

    assert case["effective_window_days"] == 30
    assert is_iso8601_timestamp(case["return_deadline_at"])
    assert case["return_deadline_at"].startswith("2026-06-01T00:00:00")
    assert case["status"] == "TRIAGE"

    line = fx.read_order_line(api, built["line_on_the_deadline"]["id"])
    assert line["status"] == "RETURN_IN_PROGRESS"


def test_one_day_earlier_delivery_puts_the_same_request_out_of_time(api):
    """PRD §2.9: "**Return window open.** The logical clock is at or before the delivery
    instant plus the effective window in days, otherwise `ERR_RETURN_WINDOW_CLOSED`
    (422). Applies to return-case creation."  The sibling line differs only in being
    delivered one day earlier, which puts its deadline one day in the past, so a single
    day separates the accepted return from the refused one and the refused line keeps
    both its delivered status and its silence in the shopper's counters.

    Design: Corner/validations/return_window_deadline_boundary_accepts_and_expired_line_rejects
    """
    built = _build_two_lines_astride_the_deadline(api)
    fx.open_case(
        api,
        built["line_on_the_deadline"]["id"],
        built["customer"]["id"],
        requested_reason_code="FIT_TOO_SMALL",
    )

    response = api.create_return_case(
        create_return_case_payload(
            built["line_one_day_past"]["id"], requested_reason_code="FIT_TOO_SMALL"
        ),
        make_customer_headers(built["customer"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_RETURN_WINDOW_CLOSED.value, 422)

    _, meta = validate_paginated(
        api.list_return_cases(
            make_merch_ops_admin_headers(),
            {
                "order_line_id": built["line_one_day_past"]["id"],
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 0

    line = fx.read_order_line(api, built["line_one_day_past"]["id"])
    assert line["status"] == "DELIVERED"

    shopper = fx.read_customer(api, built["customer"]["id"])
    assert shopper["return_case_count"] == 1
    assert shopper["purchase_line_count"] == 2
    assert shopper["return_rate_bp"] == 5000
    assert shopper["abuse_status"] == "CLEAR"


def _build_vendor_driven_to_suspension(api: ApiClient) -> dict:
    """A brand carried to seventeen correction rounds.  A single specification is
    capped at three rounds, so the rounds are spread over six auxiliary items whose
    chest grade is deliberately far outside tolerance, while one untouched draft
    specification waits on a seventh item."""
    fx.set_clock(api, SCENARIO_START)
    vendor = fx.create_vendor(api, correction_budget_cents=100000)
    target_item = fx.create_item(api, vendor["id"], sku="NRTH-TARGET")
    built = {
        "vendor": vendor,
        "target_spec": fx.create_spec(api, target_item["id"], vendor["id"]),
        "snapshots": {},
    }

    rounds = 0
    for index, rounds_on_this_item in enumerate((3, 3, 3, 3, 3, 2), start=1):
        item = fx.create_item(api, vendor["id"], sku="NRTH-AUX-%02d" % index)
        spec = fx.create_spec(
            api, item["id"], vendor["id"], size_points=VIOLATING_TWO_POINT_RUN
        )
        fx.submit_spec(api, spec["id"], vendor["id"])
        for attempt in range(rounds_on_this_item):
            if attempt:
                built["last_resubmit"] = fx.resubmit_spec(
                    api,
                    spec["id"],
                    vendor["id"],
                    size_points=VIOLATING_TWO_POINT_RUN,
                )
            verified = fx.verify_spec(api, spec["id"])
            if rounds == 0:
                built["first_verification"] = verified
            rounds += 1
            built["snapshots"][rounds] = fx.read_vendor(api, vendor["id"])
        built["last_spec"] = spec
    return built


def test_seventeen_correction_rounds_carry_the_brand_below_the_suspension_line(api):
    """PRD §2.11: "From that score the vendor's `status` follows: `SUSPENDED` when the
    score is strictly below 5,000; otherwise `PROBATION` when the score is strictly
    below 7,000 **or** when `correction_spend_cents` strictly exceeds
    `correction_budget_cents`; otherwise `ACTIVE`."  Fifteen rounds leave 5,500 basis
    points and sixteen leave 5,200, both merely probationary; the seventeenth round is
    the one that crosses the line at 4,900, and it does so on the reliability arm alone
    because 42,500 cents of correction spend is nowhere near the funded allowance.

    Design: Corner/validations/suspended_vendor_cannot_submit_a_specification
    """
    built = _build_vendor_driven_to_suspension(api)

    assert built["first_verification"]["status"] == "CORRECTION_REQUESTED"
    assert built["first_verification"]["first_violation_point"] == "CHEST"
    assert built["first_verification"]["first_violation_from_size_label"] == "S"
    assert built["last_resubmit"]["status"] == "SUBMITTED"

    fifteenth = built["snapshots"][15]
    assert fifteenth["correction_round_count"] == 15
    assert fifteenth["reliability_score_bp"] == 5500
    assert fifteenth["status"] == "PROBATION"

    sixteenth = built["snapshots"][16]
    assert sixteenth["correction_round_count"] == 16
    assert sixteenth["reliability_score_bp"] == 5200
    assert sixteenth["status"] == "PROBATION"

    seventeenth = built["snapshots"][17]
    assert seventeenth["correction_round_count"] == 17
    assert seventeenth["reliability_score_bp"] == 4900
    assert seventeenth["status"] == "SUSPENDED"
    assert seventeenth["correction_spend_cents"] == 42500
    assert seventeenth["correction_budget_cents"] == 100000


def test_a_suspended_brand_cannot_submit_even_an_untouched_specification(api):
    """PRD §2.9: "**Vendor not suspended.** The item's vendor does not have `status`
    `SUSPENDED`, otherwise `ERR_VENDOR_SUSPENDED` (409). Applies to
    measurement-specification creation, submit, and resubmit."  The specification being
    submitted has never been looked at — it is on revision round 0 and has never been
    verified — but standing is a property of the brand rather than of the document, so
    the submission is refused and the draft stays a draft.

    Design: Corner/validations/suspended_vendor_cannot_submit_a_specification
    """
    built = _build_vendor_driven_to_suspension(api)
    assert built["snapshots"][17]["status"] == "SUSPENDED"

    response = api.submit_measurement_spec(
        built["target_spec"]["id"],
        make_vendor_user_headers(built["vendor"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_VENDOR_SUSPENDED.value, 409)

    target = fx.read_spec(api, built["target_spec"]["id"])
    assert target["status"] == "DRAFT"
    assert target["revision_round"] == 0

    last = fx.read_spec(api, built["last_spec"]["id"])
    assert last["status"] == "CORRECTION_REQUESTED"
    assert last["revision_round"] == 1


def test_a_pair_naming_a_label_the_specification_lacks_writes_nothing(api):
    """PRD §2.9: "**Label membership.** Every `spec_size_label` in the submitted pairs
    exists among the verified specification's `size_points`, and every
    `chart_size_label` exists among the chart's `rows`, otherwise
    `ERR_SIZE_LABEL_NOT_IN_SPEC` (422) and nothing is written. Applies to
    size-chart-mapping creation."  The item, the standardized chart and the pinned item
    version are all in order, and the only defect is a size label the two-point
    specification never declared, so the item is left with no mapping at all rather
    than a partial one.

    Design: Corner/validations/mapping_pair_naming_a_label_outside_the_spec_returns_size_label_not_in_spec
    """
    built = fx.setup_verified_spec(api, SCENARIO_START)
    chart = fx.setup_standardized_chart(
        api, chart_code="STD-TOPS-V7", category_code="TOPS"
    )
    assert built["spec"]["status"] == "VERIFIED"
    assert chart["status"] == "STANDARDIZED"

    item_version = fx.read_item(api, built["item"]["id"])["version"]
    response = api.create_size_chart_mapping(
        create_size_chart_mapping_payload(
            built["item"]["id"],
            chart["id"],
            item_version,
            size_label_pairs=[size_label_pair("XXL", "M")],
        ),
        make_fit_analyst_headers(),
    )
    validate_error(response, ApiErrorId.ERR_SIZE_LABEL_NOT_IN_SPEC.value, 422)

    _, meta = validate_paginated(
        api.list_size_chart_mappings(
            make_merch_ops_admin_headers(),
            {"item_id": built["item"]["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 0

    item = fx.read_item(api, built["item"]["id"])
    assert item["fit_readiness"] == "UNVERIFIED"


def test_a_chart_whose_chest_ranges_overlap_refuses_to_standardize(api):
    """PRD §2.9: "**Chart row integrity.** Chart rows have `sort_index` values
    contiguous from 0, strictly increasing and non-overlapping body-chest ranges across
    consecutive rows, and non-empty values in all four conversion columns, otherwise
    `ERR_CHART_ROWS_INVALID` (422). Applies to chart standardization."  The rows carry
    contiguous sort indexes and all four conversion columns, so the chart is accepted
    as a draft; the overlap is only examined when the chart is put forward as
    authoritative, and it keeps both of its rows after the refusal.

    Design: Corner/validations/chart_standardize_with_overlapping_chest_ranges_returns_rows_invalid
    """
    fx.set_clock(api, SCENARIO_START)
    chart = fx.create_chart(
        api,
        chart_code="STD-TOPS-V8",
        category_code="TOPS",
        rows=OVERLAPPING_CHEST_ROWS,
    )
    assert chart["status"] == "DRAFT"
    assert chart["row_count"] == 2

    response = api.standardize_size_chart(chart["id"], make_merch_ops_admin_headers())
    validate_error(response, ApiErrorId.ERR_CHART_ROWS_INVALID.value, 422)

    stored = fx.read_chart(api, chart["id"])
    assert stored["status"] == "DRAFT"
    assert stored["row_count"] == 2


def test_a_fully_mapped_item_still_cannot_publish_without_its_product_page(api):
    """PRD §2.9: "**Product page complete.** The item has `model_measurements_published`
    set to true and a `detail_image_count` of at least 3, otherwise
    `ERR_PDP_ENHANCEMENT_INCOMPLETE` (422). Applies to guidance publication."  Coverage
    is complete at 10,000 basis points and every earlier gate on the publication path
    is satisfied, so the product-page requirement is the only thing left standing — and
    it is an independent gate rather than a consequence of the mapping, so the item
    stays chart-mapped.

    Design: Corner/validations/publish_guidance_without_pdp_enhancement_returns_incomplete
    """
    built = fx.setup_mapped_item(
        api, SCENARIO_START, chart_overrides={"chart_code": "STD-TOPS-V9"}
    )
    assert built["mapping"]["coverage_bp"] == 10000
    assert built["mapping"]["unmapped_size_labels"] == []

    response = api.publish_guidance(built["item"]["id"], make_fit_analyst_headers())
    validate_error(response, ApiErrorId.ERR_PDP_ENHANCEMENT_INCOMPLETE.value, 422)

    item = fx.read_item(api, built["item"]["id"])
    assert item["fit_readiness"] == "CHART_MAPPED"
    assert item["model_measurements_published"] is False
    assert item["detail_image_count"] == 0

    mapping = fx.read_mapping(api, built["mapping"]["id"])
    assert mapping["status"] == "ACTIVE"


def test_a_lever_cannot_be_scheduled_onto_an_item_off_the_storefront(api):
    """PRD §2.9: "**Deployment target listed.** The deployment's item has
    `listing_status` `LISTED`, otherwise `ERR_DEPLOYMENT_ITEM_NOT_LISTED` (409).
    Applies to deployment creation."  The window itself is well formed and overlaps
    nothing, but an item still in draft is not on the storefront where a badge could be
    shown, so the lever ends up with no deployments at all.

    Design: Corner/validations/deployment_on_a_draft_item_returns_item_not_listed
    """
    built = fx.setup_vendor_and_item(api, SCENARIO_START)
    assert built["item"]["listing_status"] == "DRAFT"

    intervention = fx.create_intervention(
        api,
        name="Fit badge pilot",
        lever="FIT_RECOMMENDATION_BADGE",
        unit_cost_cents=1500,
    )

    response = api.create_intervention_deployment(
        create_intervention_deployment_payload(
            intervention["id"],
            built["item"]["id"],
            window_start="2026-07-01T00:00:00Z",
            window_end="2026-08-01T00:00:00Z",
            spend_cents=1500,
        ),
        make_merch_ops_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_DEPLOYMENT_ITEM_NOT_LISTED.value, 409)

    _, meta = validate_paginated(
        api.list_intervention_deployments(
            make_merch_ops_admin_headers(),
            {"item_id": built["item"]["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 0

    lever = fx.read_intervention(api, intervention["id"])
    assert lever["deployment_count"] == 0

    item = fx.read_item(api, built["item"]["id"])
    assert item["listing_status"] == "DRAFT"
