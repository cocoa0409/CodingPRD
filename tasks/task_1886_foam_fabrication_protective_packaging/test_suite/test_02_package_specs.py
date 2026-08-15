"""Package specifications: required-ILD banding, submission safety gate,
state legality, filtering and pagination."""
from test_helpers import (
    NON_EXISTENT_UUID,
    SALES,
    ApiErrorId,
    assert_package_spec,
    begin_validation,
    create_customer,
    create_material,
    create_spec,
    get_spec,
    make_customer_headers,
    submit_spec,
    validate_error,
    validate_paginated,
)


def test_package_spec_computes_required_ild_at_band_boundaries(api):
    """PRD §3.2: "A required drop height under 24 inches falls in the LOW band
    with a factor of 8; a height of at least 24 but under 48 inches falls in
    the MEDIUM band with a factor of 10; a height of 48 inches or more falls
    in the HIGH band with a factor of 12." PRD §3.2: "Band lower edges are
    inclusive: a required height of exactly 24 inches is MEDIUM, and exactly
    48 inches is HIGH." PRD §3.2: "The `required_ild_lb` is the
    `product_weight_lb` multiplied by the band's factor, rounded up to the
    next whole pound."

    Design: Corner/entities/package_spec_computes_required_ild_at_band_boundaries
    """
    customer = create_customer()
    material = create_material(ild_lb_25=300)

    spec23 = create_spec(customer["id"], material["id"], part_name="S23",
                         product_weight_lb=5, required_drop_height_in=23)
    spec24 = create_spec(customer["id"], material["id"], part_name="S24",
                         product_weight_lb=5, required_drop_height_in=24)
    spec48 = create_spec(customer["id"], material["id"], part_name="S48",
                         product_weight_lb=20, required_drop_height_in=48)

    assert_package_spec(spec23)
    assert spec23["required_ild_lb"] == 40, "drop 23 -> LOW band, ceil(5*8)"
    assert spec24["required_ild_lb"] == 50, (
        "drop exactly 24 -> MEDIUM band (lower edge inclusive), ceil(5*10)"
    )
    assert spec48["required_ild_lb"] == 240, (
        "drop exactly 48 -> HIGH band (lower edge inclusive), ceil(20*12)"
    )


def test_package_spec_get_not_found_returns_404(api):
    """PRD §2.5: "Path identifiers are resolved first, then foreign keys in
    the request body, validated left to right; the first reference that does
    not exist yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/package_spec_get_not_found_returns_404
    """
    resp = api.get_package_spec(NON_EXISTENT_UUID, SALES)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_package_spec_list_filters_by_customer_and_paginates(api):
    """PRD §2.3: "Package specifications filter by `customer_id`,
    `material_id`, or `status`." PRD §2.3: "The `limit` parameter caps the
    number of items returned; it defaults to 10, with a minimum of 1 and a
    maximum of 100." PRD §2.3: "Paginated list responses carry `limit`,
    `offset`, `total_count`, and `has_more` in the `meta` object of the
    envelope."

    Design: Corner/entities/package_spec_list_filters_by_customer_and_paginates
    """
    cust_a = create_customer(name="Acme Widgets")
    cust_b = create_customer(name="Beta Corp")
    material = create_material()
    create_spec(cust_a["id"], material["id"], part_name="A1")
    create_spec(cust_a["id"], material["id"], part_name="A2",
                part_length_in=12, part_width_in=9, product_weight_lb=6)
    create_spec(cust_b["id"], material["id"], part_name="B1")

    page, meta = validate_paginated(
        api.list_package_specs(
            SALES, params={"customer_id": cust_a["id"], "limit": 1, "offset": 0},
        )
    )
    assert meta["total_count"] == 2, "customer A owns exactly two specs"
    assert len(page) == 1, "limit=1 caps the page at one row"
    assert meta["has_more"] is True
    assert page[0]["customer_id"] == cust_a["id"]

    full, meta_full = validate_paginated(
        api.list_package_specs(SALES, params={"customer_id": cust_a["id"]})
    )
    assert meta_full["total_count"] == 2
    assert meta_full["has_more"] is False
    assert len(full) == 2
    assert all(row["customer_id"] == cust_a["id"] for row in full), (
        "the customer_id filter must exclude customer B's spec"
    )


def test_spec_create_missing_required_field_returns_400(api):
    """PRD §2.5: "Required fields must be present, enum values must be valid,
    and numeric ranges must be sane — quantities positive, `contamination_pct`
    between 0 and 100 inclusive — otherwise `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.2: "A `SalesEngineer` opens a package specification by naming the
    owning `customer_id`, the selected `material_id`, a human-readable
    `part_name`, the part footprint as `part_length_in` and `part_width_in`,
    the `product_weight_lb` of the product being protected, the
    `required_drop_height_in` the packaging must survive, and the
    `max_fragility_g`, the maximum peak g-force the product tolerates."

    Design: Corner/validations/spec_create_missing_required_field_returns_400
    """
    customer = create_customer()
    material = create_material()
    payload = {
        "customer_id": customer["id"],
        "material_id": material["id"],
        "part_name": "Widget Tray",
        "part_length_in": 10,
        "part_width_in": 8,
        "product_weight_lb": 5,
        "required_drop_height_in": 30,
        # max_fragility_g omitted
    }
    resp = api.create_package_spec(payload, SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_submit_with_insufficient_ild_rejected(api):
    """PRD §3.2: "Submitting moves the specification from `DRAFT` to
    `SUBMITTED` and enforces the cushioning safety margin: the selected
    material's `ild_lb_25` must be at least the specification's
    `required_ild_lb`, or the submission is rejected with
    `ERR_ILD_SAFETY_MARGIN` (HTTP 422)."

    Design: Corner/validations/submit_with_insufficient_ild_rejected
    """
    customer = create_customer()
    material = create_material(foam_family="PU", density_pcf=1.2, ild_lb_25=40,
                               cost_per_board_ft_cents=200,
                               scrap_credit_per_lb_cents=10)
    # weight 5, drop 30 -> MEDIUM band -> required_ild_lb 50 > material ild 40
    spec = create_spec(customer["id"], material["id"])
    assert spec["required_ild_lb"] == 50

    resp = api.submit_spec(spec["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_ILD_SAFETY_MARGIN)
    assert get_spec(spec["id"])["status"] == "DRAFT", (
        "a rejected submission leaves the spec in DRAFT"
    )


def test_spec_double_submit_rejected(api):
    """PRD §3.2: "Submitting moves the specification from `DRAFT` to
    `SUBMITTED` and enforces the cushioning safety margin: the selected
    material's `ild_lb_25` must be at least the specification's
    `required_ild_lb`, or the submission is rejected with
    `ERR_ILD_SAFETY_MARGIN` (HTTP 422)." PRD §2.5: "The target resource must
    be in a valid from-state for the requested transition, and cross-entity
    state gates must hold — rejected as `ERR_INVALID_STATE`,
    `ERR_SPEC_NOT_APPROVED`, `ERR_PROGRAM_NOT_ACTIVE`,
    `ERR_TOOLING_NOT_IN_SERVICE`, or `ERR_PROGRAM_HAS_OPEN_RELEASES` (all HTTP
    409)."

    Design: Corner/state_machines/spec_double_submit_rejected
    """
    customer = create_customer()
    material = create_material()
    spec = create_spec(customer["id"], material["id"])
    submit_spec(spec["id"])

    resp = api.submit_spec(spec["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_spec(spec["id"])["status"] == "SUBMITTED", (
        "a rejected second submit changes nothing"
    )


def test_spec_approve_before_validated_rejected(api):
    """PRD §3.2: "When the specification has reached `VALIDATED`, the owning
    `Customer` signs off, moving it from `VALIDATED` to `APPROVED`; the
    caller's `X-User-ID` must equal the specification's `customer_id`, or the
    approval is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)." PRD
    §2.5: "The target resource must be in a valid from-state for the
    requested transition, and cross-entity state gates must hold — rejected
    as `ERR_INVALID_STATE`, `ERR_SPEC_NOT_APPROVED`, `ERR_PROGRAM_NOT_ACTIVE`,
    `ERR_TOOLING_NOT_IN_SERVICE`, or `ERR_PROGRAM_HAS_OPEN_RELEASES` (all HTTP
    409)."

    Design: Corner/state_machines/spec_approve_before_validated_rejected
    """
    customer = create_customer()
    material = create_material()
    spec = create_spec(customer["id"], material["id"])
    submit_spec(spec["id"])
    begin_validation(spec["id"])

    resp = api.approve_spec(spec["id"], make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_spec(spec["id"])["status"] == "IN_VALIDATION"
