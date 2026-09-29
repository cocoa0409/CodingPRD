"""Half-open PriceRule effectivity: abutting is legal, one second of overlap is not."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, ApiErrorId,
    factories,
    set_clock, create_facility, create_revenue_code, create_price_rule,
    ANALYST,
)

R1_FROM = "2026-09-01T00:00:00Z"
R1_TO = "2026-12-01T00:00:00Z"


def _setup():
    set_clock("2026-08-01T00:00:00Z")
    facility = create_facility(
        name="Interval General", cms_certification_number="CCN-2193-I",
        rounding_mode="NEAREST_CENT", aggregate_markup_limit_bp=40000,
    )
    revenue_code = create_revenue_code(
        code="0300", description="Laboratory", requires_hcpcs=False,
        allowed_code_types=["CDM_INTERNAL", "REV_ONLY"],
        pricing_class="PROCEDURE", status="ACTIVE",
    )
    rule = create_price_rule(
        facility["id"], revenue_code["id"],
        pricing_method="FLAT_FEE", flat_fee_cents=50000,
        effective_from=R1_FROM, effective_to=R1_TO,
    )
    return {"facility": facility, "revenue_code": revenue_code, "price_rule": rule}


def _new_rule_payload(s, **overrides):
    fields = {"pricing_method": "FLAT_FEE", "flat_fee_cents": 60000}
    fields.update(overrides)
    return factories.create_price_rule_payload(
        s["facility"]["id"], s["revenue_code"]["id"], **fields
    )


def test_a_rule_starting_exactly_where_the_previous_one_ends_abuts_and_is_accepted():
    """PRD §3.2: "Effectivity is half-open: `effective_from` is the inclusive start and
    `effective_to` the exclusive end, with null meaning open-ended."
    PRD §3.2: "Because the intervals are half-open, an existing rule whose `effective_to`
    equals the new rule's `effective_from` abuts rather than overlaps and is entirely legal."
    PRD §2.5: "Consequently two rules for the same scope may abut — one ending exactly where
    the next begins — without colliding."

    Design: Difficulty/resource_temporal_overlap/resource_temporal_overlap__price_rule_half_open_abut_legal_then_one_second_collision
    """
    s = _setup()
    assert s["price_rule"]["status"] == "ACTIVE"
    assert s["price_rule"]["effective_to"].startswith("2026-12-01T00:00:00")

    abutting = validate_success(
        api_client.create_price_rule(
            _new_rule_payload(s, effective_from=R1_TO, effective_to=None), ANALYST
        ),
        201,
    )
    assert abutting["effective_from"].startswith("2026-12-01T00:00:00")
    assert abutting["effective_to"] is None, "a null effective_to means open-ended"
    assert abutting["status"] == "ACTIVE"
    assert abutting["superseded_by_rule_id"] is None, (
        "no supersede_rule_id was named, so nothing was replaced"
    )

    rows, _meta = validate_paginated(
        api_client.list_price_rules(
            ANALYST, params={"facility_id": s["facility"]["id"], "status": "ACTIVE"}
        )
    )
    assert len(rows) == 2


def test_a_rule_starting_one_second_before_that_boundary_collides():
    """PRD §3.2: "Creating a rule triggers a scope-key overlap check against other rules of the
    same `(facility_id, revenue_code_id)` whose `status` is `ACTIVE`; if the new interval
    intersects an existing one the create is refused with `ERR_PRICE_RULE_OVERLAP`."
    PRD §2.5: "A rule is in force when its `effective_from` is at or before now and, if
    `effective_to` is present, when now is strictly earlier than `effective_to`."

    Design: Difficulty/resource_temporal_overlap/resource_temporal_overlap__price_rule_half_open_abut_legal_then_one_second_collision
    """
    s = _setup()
    validate_success(
        api_client.create_price_rule(
            _new_rule_payload(s, effective_from=R1_TO, effective_to=None), ANALYST
        ),
        201,
    )

    validate_error(
        api_client.create_price_rule(
            _new_rule_payload(
                s, flat_fee_cents=70000,
                effective_from="2026-11-30T23:59:59Z",
                effective_to="2027-06-01T00:00:00Z",
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_PRICE_RULE_OVERLAP.value,
        409,
    )

    survivor = validate_success(
        api_client.get_price_rule(s["price_rule"]["id"], ANALYST), 200
    )
    assert survivor["status"] == "ACTIVE"
    assert survivor["effective_to"].startswith("2026-12-01T00:00:00"), (
        "a refused create must not truncate the incumbent interval"
    )
    assert survivor["superseded_by_rule_id"] is None

    rows, _meta = validate_paginated(
        api_client.list_price_rules(
            ANALYST, params={"facility_id": s["facility"]["id"], "status": "ACTIVE"}
        )
    )
    assert len(rows) == 2, (
        f"the rejected third rule was never persisted: got {len(rows)} rows"
    )
