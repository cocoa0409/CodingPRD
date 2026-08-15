"""Quote line intake, structural/compatibility validation, and pricing rules."""
from test_helpers import (
    EST,
    ApiErrorId,
    PINNED_TIERS_2,
    create_customer,
    create_draft_quote,
    create_grade,
    create_quote_line_payload,
    get_order_lines,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_quote_line_created_estimated(api):
    """PRD §3.3: "A freshly added line starts in ESTIMATED status."

    Design: Corner/entities/quote_line_computed_fields_ignore_client_input
    """
    grade = create_grade()
    customer = create_customer()
    empty = validate_success(
        api.create_quote({"customer_id": customer["id"], "expedite_tier": "STANDARD"},
                         EST),
        201,
    )
    resp = api.add_quote_line(
        empty["id"],
        create_quote_line_payload(grade["id"], bbox_width_mm=100,
                                  bbox_height_mm=100, qty=1),
        EST,
    )
    line = validate_success(resp, 201)
    assert line["status"] == "ESTIMATED"
    assert line["quote_id"] == empty["id"]
    assert line["grade_id"] == grade["id"]
    assert line["bbox_width_mm"] == 100
    assert line["qty"] == 1


def test_fk_reverse_reachability_quote_lines(api):
    """PRD §2.8: "The API has a flat topology: every resource is addressable by
    its `id` at the top level, and some collections are additionally reachable
    nested under a parent — lines under their quote ..."

    Design: Corner/entities/fk_reverse_reachability_quote_lines
    """
    grade = create_grade()
    customer = create_customer()
    quote = create_draft_quote(
        customer["id"], grade["id"],
        line_overrides={"bbox_width_mm": 50, "bbox_height_mm": 50},
    )

    lines, _meta = validate_paginated(api.list_quote_lines(quote["id"], EST))
    assert len(lines) == 1
    direct = validate_success(api.get_quote_line(lines[0]["id"], EST))
    assert direct["id"] == lines[0]["id"]
    assert direct["quote_id"] == quote["id"]


def test_thickness_tier_unresolved_on_quote_create(api):
    """PRD §3.3: "Structural failures are rejected with
    `ERR_INVALID_LINE_SPEC`, with `ERR_THICKNESS_TIER_UNRESOLVED` as the
    tier-specific form when the gauge exceeds every tier's `max_thickness_mm`."
    PRD §3.3: "These two checks guard all three line-bearing operations —
    quote creation with initial lines, line addition, and pricing."

    Design: Corner/validations/thickness_tier_unresolved_specific_error
    """
    grade = create_grade(tiers=[{"max_thickness_mm": 2.0, "tier_index": 0}])
    customer = create_customer()
    line = create_quote_line_payload(grade["id"], thickness_mm=3.0,
                                     bbox_width_mm=50, bbox_height_mm=50)
    resp = api.create_quote(
        {"customer_id": customer["id"], "expedite_tier": "STANDARD",
         "lines": [line]},
        EST,
    )
    validate_error(resp, ApiErrorId.ERR_THICKNESS_TIER_UNRESOLVED, 422)


def test_thickness_tier_unresolved_on_line_add(api):
    """PRD §3.3: "Structural failures are rejected with
    `ERR_INVALID_LINE_SPEC`, with `ERR_THICKNESS_TIER_UNRESOLVED` as the
    tier-specific form when the gauge exceeds every tier's `max_thickness_mm`."
    PRD §3.3: "These two checks guard all three line-bearing operations —
    quote creation with initial lines, line addition, and pricing."

    Design: Corner/validations/thickness_tier_unresolved_specific_error
    """
    grade = create_grade(tiers=[{"max_thickness_mm": 2.0, "tier_index": 0}])
    customer = create_customer()
    quote = validate_success(
        api.create_quote({"customer_id": customer["id"]}, EST), 201,
    )
    resp = api.add_quote_line(
        quote["id"],
        create_quote_line_payload(grade["id"], thickness_mm=3.0),
        EST,
    )
    validate_error(resp, ApiErrorId.ERR_THICKNESS_TIER_UNRESOLVED, 422)


def test_weld_on_incompatible_grade_rejected(api):
    """PRD §3.3: "POWDER requires the grade's `powder_compatible` flag, any
    positive `weld_inches` requires `weld_compatible`, and PLATING or ANODIZING
    requires an ACTIVE outside vendor of the matching process; violations are
    rejected with `ERR_FINISH_NOT_COMPATIBLE`."

    Design: Corner/validations/weld_on_incompatible_grade_rejected
    """
    no_weld = create_grade(weld_compatible=False,
                           tiers=[{"max_thickness_mm": 2.0, "tier_index": 0}])
    customer = create_customer()
    bad_line = create_quote_line_payload(no_weld["id"], bbox_width_mm=50,
                                         bbox_height_mm=50, weld_inches=5)
    resp = api.create_quote(
        {"customer_id": customer["id"], "expedite_tier": "STANDARD",
         "lines": [bad_line]},
        EST,
    )
    validate_error(resp, ApiErrorId.ERR_FINISH_NOT_COMPATIBLE, 422)


def test_weld_on_compatible_grade_prices_fine(api):
    """PRD §3.3: "any positive `weld_inches` requires `weld_compatible` ...
    violations are rejected with `ERR_FINISH_NOT_COMPATIBLE`." (The compatible
    flag admits the same line.)

    Design: Corner/validations/weld_on_incompatible_grade_rejected
    """
    ok_grade = create_grade(tiers=[{"max_thickness_mm": 2.0, "tier_index": 0}])
    customer = create_customer()
    quote = create_draft_quote(
        customer["id"], ok_grade["id"],
        line_overrides={"bbox_width_mm": 50, "bbox_height_mm": 50,
                        "hole_count": 0, "corner_fillet_count": 0,
                        "bend_count": 0, "weld_inches": 5},
    )
    priced = validate_success(api.price_quote(quote["id"], quote["version"], EST))
    assert priced["status"] == "PRICED"


def test_qty_discount_tier_nine_gets_no_discount(api):
    """PRD §3.3: "The tiers are inclusive and evaluated top-down: a `qty` of at
    least 50 earns 12 percent off, at least 20 earns 8 percent, at least 10
    earns 4 percent, and smaller quantities earn none; the line records the
    winning fraction as `qty_discount_pct`."

    Design: Difficulty/boundary_precision_check/qty_discount_tier_boundary_9_vs_10
    """
    grade = create_grade(tiers=PINNED_TIERS_2)
    customer = create_customer()
    q9 = create_draft_quote(customer["id"], grade["id"], qty=9)
    priced9 = validate_success(api.price_quote(q9["id"], q9["version"], EST))

    line9 = get_order_lines(q9["id"])[0]
    assert line9["qty_discount_pct"] == 0, "qty 9 is below the inclusive 10 tier"
    assert line9["line_total_cents"] == line9["line_base_cents"], (
        "no discount and STANDARD multiplier: per-part total equals per-part base"
    )
    assert priced9["quoted_total_cents"] == line9["line_total_cents"] * 9


def test_qty_discount_tier_ten_gets_four_percent(api):
    """PRD §3.3: "The tiers are inclusive and evaluated top-down: a `qty` of at
    least 50 earns 12 percent off, at least 20 earns 8 percent, at least 10
    earns 4 percent, and smaller quantities earn none; the line records the
    winning fraction as `qty_discount_pct`."

    Design: Difficulty/boundary_precision_check/qty_discount_tier_boundary_9_vs_10
    """
    grade = create_grade(tiers=PINNED_TIERS_2)
    customer = create_customer()
    q9 = create_draft_quote(customer["id"], grade["id"], qty=9)
    q10 = create_draft_quote(customer["id"], grade["id"], qty=10)
    validate_success(api.price_quote(q9["id"], q9["version"], EST))
    validate_success(api.price_quote(q10["id"], q10["version"], EST))

    line9 = get_order_lines(q9["id"])[0]
    line10 = get_order_lines(q10["id"])[0]
    assert line10["qty_discount_pct"] == 0.04, "qty 10 crosses the inclusive tier"
    assert line10["line_total_cents"] < line9["line_total_cents"], (
        "one unit crosses the tier and the per-part total drops"
    )
