"""Pagination bounds on a list endpoint, and the empty rule candidate set below the schema check."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, ApiErrorId, factories,
    setup_base, create_item, create_active_item, read_item, set_clock,
    ANALYST,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-PAGE",
        "rounding_mode": "NEAREST_CENT", "aggregate_markup_limit_bp": 40000,
    },
    revenue_code_overrides={
        "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
        "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
        "pricing_class": "PROCEDURE", "status": "ACTIVE",
    },
    department_overrides={
        "name": "Cardiac Cath Lab", "cost_center_code": "CC-100",
        "allowed_revenue_code_values": [],
    },
    price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z"},
)
PRICING = dict(cost_basis_cents=100000, medicare_rate_cents=50000,
               market_p75_cents=900000, effective_from="2026-09-01T00:00:00Z")


def test_limit_is_the_closed_range_one_to_one_hundred_and_the_window_walks_creation_order():
    """PRD §2.3: "The `limit` parameter defaults to 10 when omitted, may be no smaller than 1, and may
    be no larger than 100. The `offset` parameter defaults to 0 and may be no smaller than 0. A `limit`
    outside the inclusive range from 1 to 100, or a negative `offset`, is a schema failure and is
    rejected with `ERR_VALIDATION` (HTTP 422)."
    PRD §2.3: "The four pagination fields — `limit`, `offset`, `total_count` and `has_more` — appear
    inside `meta` on list responses. `total_count` is the number of records matching the filters before
    pagination is applied, and `has_more` is true when records remain beyond the current window."
    PRD §2.3: "Unless a specific endpoint's narrative in §3 pins a different order, list results are
    sorted by `created_at` ascending."

    Design: Corner/validations/pagination_bounds_reject_limit_zero_and_limit_101_and_accept_the_inclusive_ends
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    facility_id = base["facility"]["id"]
    first = create_item(base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
                        code_type="CPT", code_value="93458", **PRICING)
    second = create_item(base, cdm_number="CDM-1002", description="CARDIAC CATH COMPLEX",
                         code_type="CPT", code_value="93460", **PRICING)
    third = create_item(base, cdm_number="CDM-1003", description="CARDIAC CATH ADD ON",
                        code_type="CPT", code_value="93461", **PRICING)

    for bad in ({"limit": 0}, {"limit": 101}, {"limit": 10, "offset": -1}):
        validate_error(
            api_client.list_charge_items(ANALYST, {"facility_id": facility_id, **bad}),
            ApiErrorId.ERR_VALIDATION.value, 422,
        )

    rows, meta = validate_paginated(api_client.list_charge_items(
        ANALYST, {"facility_id": facility_id, "limit": 1, "offset": 1}))
    assert len(rows) == 1
    assert meta["total_count"] == 3
    assert meta["limit"] == 1
    assert meta["offset"] == 1
    assert meta["has_more"] is True
    assert rows[0]["id"] == second["id"], "creation order is stable across pages"

    all_rows, all_meta = validate_paginated(api_client.list_charge_items(
        ANALYST, {"facility_id": facility_id, "limit": 100, "offset": 0}))
    assert len(all_rows) == 3
    assert all_meta["total_count"] == 3
    assert all_meta["has_more"] is False
    assert [row["id"] for row in all_rows] == [first["id"], second["id"], third["id"]]

    draft_rows, draft_meta = validate_paginated(api_client.list_charge_items(
        ANALYST, {"facility_id": facility_id, "limit": 100, "offset": 0,
                  "lifecycle_status": "DRAFT"}))
    assert draft_meta["total_count"] == 3
    assert [row["id"] for row in draft_rows] == [first["id"], second["id"], third["id"]]


def test_the_schema_check_beats_the_empty_candidate_set_and_a_new_rule_reopens_pricing():
    """PRD §3.2: "If the candidate set is empty, the operation fails with
    `ERR_NO_APPLICABLE_PRICE_RULE` (HTTP 422)."
    PRD §3.5: "Because the dry run runs the rule selector, a submission against an item with no
    applicable rule fails with `ERR_NO_APPLICABLE_PRICE_RULE`."
    PRD §3.4: "On success, in order: `prior_gross_charge_cents` takes the item's outgoing
    `gross_charge_cents` before it is overwritten; `gross_charge_cents` takes the computed output;
    `applied_price_rule_id` records the selected rule; `price_conflict` is set according to whether the
    Medicare floor exceeded the market cap; `price_status` becomes `PRICED_CURRENT`; and the item's
    `version` advances by 1."

    Design: Corner/validations/schema_check_precedes_the_missing_price_rule_and_a_new_rule_reopens_pricing
    """
    set_clock("2026-09-01T00:00:00Z")
    # The markup ceiling is lifted to 50000 bp so that the closing submission is judged only by the
    # rule selector: its projected ratio of 41667 bp would otherwise trip the §3.2 markup gate, which
    # the PRD evaluates at change-request creation.
    base = setup_base(
        facility_overrides={
            "name": "Mercy General", "cms_certification_number": "CCN-2193-NORULE",
            "rounding_mode": "NEAREST_CENT", "aggregate_markup_limit_bp": 50000,
        },
        revenue_code_overrides=MERCY["revenue_code_overrides"],
        department_overrides=MERCY["department_overrides"],
        price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z",
                              "effective_to": "2026-10-01T00:00:00Z"},
    )
    facility_id = base["facility"]["id"]
    rule_a = base["price_rule"]
    item = create_active_item(base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
                              code_type="CPT", code_value="93458", **PRICING)
    assert item["gross_charge_cents"] == 240000
    assert item["version"] == 5

    set_clock("2026-11-01T00:00:00Z")
    validate_error(
        api_client.reprice_charge_item(item["id"], ANALYST),
        ApiErrorId.ERR_NO_APPLICABLE_PRICE_RULE.value, 422,
    )
    untouched = read_item(item["id"])
    assert untouched["gross_charge_cents"] == 240000
    assert untouched["version"] == 5, "the failed reprice mutated nothing"

    def request_body(justification):
        return factories.create_change_request_payload(
            base["department"]["id"], item["id"], "PRICE_CHANGE",
            justification=justification, proposed_cost_basis_cents=120000,
        )

    short = request_body("Cost up")
    assert len(short["justification"]) == 7
    validate_error(
        api_client.create_change_request(short, base["manager_headers"]),
        ApiErrorId.ERR_VALIDATION.value, 422,
    )
    validate_error(
        api_client.create_change_request(
            request_body("Supply cost increase effective November"), base["manager_headers"]),
        ApiErrorId.ERR_NO_APPLICABLE_PRICE_RULE.value, 422,
    )

    assert validate_success(api_client.get_price_rule(rule_a["id"], ANALYST), 200)["status"] \
        == "ACTIVE", "an expired interval does not change the rule's status"

    rule_b = validate_success(api_client.create_price_rule(
        factories.create_price_rule_payload(
            facility_id, base["revenue_code"]["id"],
            pricing_method="FLAT_FEE", flat_fee_cents=500000,
            effective_from="2026-11-01T00:00:00Z", effective_to=None,
            min_medicare_multiple_bp=12000, market_cap_multiple_bp=11000,
        ), ANALYST), 201)

    repriced = validate_success(api_client.reprice_charge_item(item["id"], ANALYST), 200)
    assert repriced["gross_charge_cents"] == 500000
    assert repriced["prior_gross_charge_cents"] == 240000
    assert repriced["applied_price_rule_id"] == rule_b["id"]
    assert repriced["price_status"] == "PRICED_CURRENT"

    request = validate_success(api_client.create_change_request(
        request_body("Supply cost increase effective November"), base["manager_headers"]), 201)
    assert request["status"] == "SUBMITTED"
    assert request["projected_gross_charge_cents"] == 500000, (
        "FLAT_FEE ignores proposed_cost_basis_cents entirely"
    )
    assert request["projected_markup_ratio_bp"] == 41667, (
        "500000 times 10000 divided by 120000, rounded half up"
    )
