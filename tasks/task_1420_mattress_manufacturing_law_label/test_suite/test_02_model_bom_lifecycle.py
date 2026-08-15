"""Model authoring, BOM costing, and the certification lifecycle (PRD §3.2–§3.3)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    validate_success,
    validate_error,
    get_success_data,
    assert_model,
    assert_bom_line,
    create_model_payload,
    create_bom_line_payload,
    create_certificate_payload,
    create_production_order_payload,
    create_model_with_bom,
    create_retailer_account,
    submit_model_for_certification,
    setup_active_model,
)

PM = TEST_USERS["plant_manager_headers"]
CO1 = TEST_USERS["compliance_creator_headers"]
CO2 = TEST_USERS["compliance_approver_headers"]
LS1 = TEST_USERS["line_supervisor_headers"]


def test_model_created_in_draft_with_zero_bom_cost(api):
    """PRD §3.2: "The model is born in `DRAFT` status with `bom_cost_cents`
    initialized to zero."

    Design: Corner/entities/model_create_response_immediate_consistency
    """
    resp = api.create_model(create_model_payload(quilt_pattern="ZIGZAG"), PM)
    model = validate_success(resp, expected_status=201)
    assert_model(model)
    assert model["status"] == "DRAFT"
    assert model["bom_cost_cents"] == 0
    assert model["quilt_pattern"] == "ZIGZAG"


def test_get_model_with_unknown_id_returns_not_found(api):
    """PRD §2.8: "Unknown ids produce the resource's dedicated 404:
    `ERR_MODEL_NOT_FOUND`, `ERR_BOM_LINE_NOT_FOUND`,
    `ERR_CERTIFICATE_NOT_FOUND`, `ERR_LABEL_NOT_FOUND`, `ERR_SPEC_NOT_FOUND`,
    `ERR_RETAILER_NOT_FOUND`, `ERR_FOAM_BATCH_NOT_FOUND`,
    `ERR_QUILT_RUN_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
    `ERR_SHIPMENT_NOT_FOUND`, `ERR_RETURN_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
    or `ERR_INTAKE_NOT_FOUND`."

    Design: Corner/entities/model_get_not_found_returns_404
    """
    resp = api.get_model(NON_EXISTENT_UUID, PM)
    validate_error(resp, ApiErrorId.ERR_MODEL_NOT_FOUND)


def test_bom_line_without_unit_cost_rejected(api):
    """PRD §2.8: "4. Request-body well-formedness (`ERR_VALIDATION_FAILED`,
    400): required input fields present, enum values valid, `quantity` at
    least 1, masses strictly greater than zero, `unit_price_cents` strictly
    greater than zero, `expires_on` strictly after `issued_on`."
    PRD §3.2: "Each line carries a `component_type` — one of `FOAM_CORE`,
    `MEMORY_LAYER`, `FIRE_BARRIER`, `TICKING`, `QUILT_PANEL`, `FOUNDATION`, or
    `THREAD` — a supplier `material_code`, a `quantity_per_unit` that may be
    fractional but must be greater than zero, and a `unit_cost_cents` that
    must be zero or greater."

    Design: Corner/entities/bom_line_missing_required_field_returns_400
    """
    built = create_model_with_bom(bom_lines=[])
    payload = {
        "component_type": "THREAD",
        "material_code": "MAT-TH",
        "quantity_per_unit": 1,
    }
    resp = api.create_bom_line(built["model"]["id"], payload, PM)
    validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED)


def test_bom_line_costs_rounded_half_up_per_line(api):
    """PRD §3.2: "Each line's `line_cost_cents` is the product of
    `quantity_per_unit` and `unit_cost_cents`, rounded half up to integer
    cents."

    Design: Difficulty/combinatorial_formula/bom_per_line_rounding_then_sum
    """
    built = create_model_with_bom(bom_lines=[])
    model_id = built["model"]["id"]

    line1 = validate_success(api.create_bom_line(
        model_id,
        create_bom_line_payload(
            component_type="QUILT_PANEL", material_code="MAT-Q1",
            quantity_per_unit=1.5, unit_cost_cents=333, filling_content_code=None,
        ),
        PM,
    ), expected_status=201)
    assert_bom_line(line1)
    assert line1["line_cost_cents"] == 500, (
        f"1.5 x 333 rounds half up to 500, got {line1['line_cost_cents']}"
    )

    line2 = validate_success(api.create_bom_line(
        model_id,
        create_bom_line_payload(
            component_type="FOUNDATION", material_code="MAT-FD",
            quantity_per_unit=0.5, unit_cost_cents=199, filling_content_code=None,
        ),
        PM,
    ), expected_status=201)
    assert line2["line_cost_cents"] == 100, (
        f"0.5 x 199 rounds half up to 100, got {line2['line_cost_cents']}"
    )


def test_model_bom_cost_sums_per_line_rounded_values(api):
    """PRD §3.2: "The model's `bom_cost_cents` is then the sum of those
    per-line rounded values across every line of the model, regardless of
    component type. The rounding order is pinned — round each line first, then
    sum; summing the unrounded products and rounding once at the end yields
    different cents and is not the contract."

    Design: Difficulty/combinatorial_formula/bom_per_line_rounding_then_sum
    """
    built = create_model_with_bom(bom_lines=[])
    model_id = built["model"]["id"]
    for payload in (
        create_bom_line_payload(
            component_type="QUILT_PANEL", material_code="MAT-Q1",
            quantity_per_unit=1.5, unit_cost_cents=333, filling_content_code=None,
        ),
        create_bom_line_payload(
            component_type="FOUNDATION", material_code="MAT-FD",
            quantity_per_unit=0.5, unit_cost_cents=199, filling_content_code=None,
        ),
        create_bom_line_payload(
            component_type="THREAD", material_code="MAT-TH",
            quantity_per_unit=3, unit_cost_cents=100, filling_content_code=None,
        ),
    ):
        get_success_data(api.create_bom_line(model_id, payload, PM))

    model = get_success_data(api.get_model(model_id, PM))
    # 500 + 100 + 300 = 900 (sum-then-round would give 899 — not the contract)
    assert model["bom_cost_cents"] == 900, (
        f"bom_cost_cents must sum per-line rounded values: got {model['bom_cost_cents']}"
    )


def test_bom_edit_rejected_on_stale_model_version(api):
    """PRD §2.7: "Editing a BOM line requires `expected_model_version` matching
    the parent model's current `version`, because BOM edits change
    `bom_cost_cents` and any future label content, and each edit bumps the
    model's version."

    Design: Corner/complexity_layers/occ_bom_edit_stale_model_version
    """
    built = create_model_with_bom(
        bom_lines=[create_bom_line_payload(
            component_type="THREAD", material_code="MAT-TH",
            quantity_per_unit=1, unit_cost_cents=10, filling_content_code=None,
        )]
    )
    model_id = built["model"]["id"]
    line_id = built["lines"][0]["id"]
    observed_version = get_success_data(api.get_model(model_id, PM))["version"]

    edited = validate_success(api.update_bom_line(
        model_id, line_id,
        {"quantity_per_unit": 3, "expected_model_version": observed_version},
        PM,
    ))
    assert edited["line_cost_cents"] == 30

    stale = api.update_bom_line(
        model_id, line_id,
        {"quantity_per_unit": 4, "expected_model_version": observed_version},
        PM,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)


def test_submit_for_certification_requires_bom_line(api):
    """PRD §3.3: "the model must have at least one BOM line, otherwise the
    submission is rejected with `ERR_MODEL_HAS_NO_BOM` (409)"

    Design: Corner/validations/submit_without_bom_rejected
    """
    built = create_model_with_bom(bom_lines=[])
    resp = api.submit_model_for_certification(built["model"]["id"], PM)
    validate_error(resp, ApiErrorId.ERR_MODEL_HAS_NO_BOM)


def test_discontinue_blocked_while_open_order_exists(api):
    """PRD §3.3: "Discontinuing moves `ACTIVE` → `DISCONTINUED` and is refused
    with `ERR_OPEN_ORDERS_EXIST` (409) while any production order for the
    model sits in `PLANNED`, `MATERIAL_ALLOCATED`, `IN_PRODUCTION`,
    `QC_PENDING`, or `QC_HOLD`."

    Design: Corner/validations/discontinue_blocked_by_open_order
    """
    retailer = create_retailer_account()
    ctx = setup_active_model()
    order = get_success_data(api.create_production_order(
        create_production_order_payload(
            model_id=ctx["model"]["id"], retailer_id=retailer["id"],
            destination_state_code="NV",
        ),
        PM,
    ))
    assert order["production_status"] == "PLANNED"

    blocked = api.discontinue_model(ctx["model"]["id"], PM)
    validate_error(blocked, ApiErrorId.ERR_OPEN_ORDERS_EXIST)

    get_success_data(api.cancel_order(order["id"], PM))
    discontinued = validate_success(api.discontinue_model(ctx["model"]["id"], PM))
    assert discontinued["status"] == "DISCONTINUED"


def test_line_supervisor_cannot_certify_model(api):
    """PRD §2.1: "If the caller's role is well-formed but not in the endpoint's
    authorized role list, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."
    PRD §4: POST /plant/models/{id}/certify is authorized for
    ComplianceOfficer only.

    Design: Corner/rbac/line_supervisor_cannot_certify_model
    """
    built = create_model_with_bom()
    submit_model_for_certification(built["model"]["id"])
    resp = api.certify_model(built["model"]["id"], LS1)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_certificate_with_inverted_dates_rejected(api):
    """PRD §3.3: "A `ComplianceOfficer` submits each certificate with a
    `cert_type` — `FLAMMABILITY_16CFR1633`, `PROP65_CA`, or `TB117` — a
    `jurisdiction_state_code` (the two-letter state code the certificate
    covers; `FLAMMABILITY_16CFR1633` is federal and uses the state code
    `US`), and the `issued_on` / `expires_on` timestamps, with `expires_on`
    required to be strictly after `issued_on`."
    PRD §2.8: "4. Request-body well-formedness (`ERR_VALIDATION_FAILED`, 400):
    required input fields present, enum values valid, `quantity` at least 1,
    masses strictly greater than zero, `unit_price_cents` strictly greater
    than zero, `expires_on` strictly after `issued_on`."

    Design: Corner/entities/certificate_inverted_dates_rejected
    """
    built = create_model_with_bom()
    submit_model_for_certification(built["model"]["id"])
    resp = api.create_certificate(
        built["model"]["id"],
        create_certificate_payload(
            cert_type="PROP65_CA", jurisdiction_state_code="CA",
            issued_on="2027-01-01T00:00:00Z", expires_on="2026-01-01T00:00:00Z",
        ),
        CO1,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED)
