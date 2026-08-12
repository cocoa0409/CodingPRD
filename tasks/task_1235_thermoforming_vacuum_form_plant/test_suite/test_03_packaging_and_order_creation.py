"""Packaging spec decisions and production order creation gates (PRD §3.4, §3.5)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_production_order,
    create_custom_spec,
    create_order,
    create_production_order_payload,
    create_spec_decide_payload,
    create_stock_spec,
    create_tool_production,
    create_tool_prototype,
    issue_certificate,
    validate_error,
    validate_success,
)

_PACKAGING = TEST_USERS["packaging_engineer_headers"]
_MANAGER = TEST_USERS["plant_manager_headers"]
_SCHEDULER = TEST_USERS["production_scheduler_headers"]


def test_decide_stock_spec_rejected(api):
    """PRD §3.4: "a `STOCK` spec is born `ACTIVE` and immediately usable, while
    a `CUSTOM` spec is born `PENDING_APPROVAL` and must survive a decision."
    PRD §3.4: "The decision belongs to `PlantManager` and only makes sense from
    `PENDING_APPROVAL`; deciding a spec in any other state is
    `ERR_INVALID_SPEC_STATE`."

    Design: Corner/errors/decide_stock_spec_rejected
    """
    spec = create_stock_spec(spec_code="S-ERR1", per_pack_cost=0.30)
    assert spec["status"] == "ACTIVE", f"STOCK spec must be born ACTIVE, got {spec['status']}"
    res = api.decide_packaging_spec(spec["id"], create_spec_decide_payload("APPROVED"), _MANAGER)
    validate_error(res, ApiErrorId.ERR_INVALID_SPEC_STATE)


def test_decide_custom_spec_without_cert_rejected(api):
    """PRD §3.4: "A `decision` of `APPROVED` is certificate-gated: a currently
    valid certificate must exist with `subject_type` `PACKAGING_SPEC` naming
    this spec, at a `grade` at least the spec's `cleanliness_grade`, otherwise
    `ERR_CERTIFICATE_INVALID`."

    Design: Corner/validations/decide_custom_spec_without_cert_rejected
    """
    spec = create_custom_spec(spec_code="S-V13", cleanliness_grade="FOOD", per_pack_cost=0.90)
    assert spec["status"] == "PENDING_APPROVAL"
    res = api.decide_packaging_spec(spec["id"], create_spec_decide_payload("APPROVED"), _MANAGER)
    validate_error(res, ApiErrorId.ERR_CERTIFICATE_INVALID)


def test_decide_custom_spec_with_cert_succeeds(api):
    """PRD §3.4: "A `decision` of `APPROVED` is certificate-gated: a currently
    valid certificate must exist with `subject_type` `PACKAGING_SPEC` naming
    this spec, at a `grade` at least the spec's `cleanliness_grade`, otherwise
    `ERR_CERTIFICATE_INVALID`."
    PRD §3.4: "Either way the decider's `X-User-ID` is recorded as
    `decided_by_user_id` — null until this point — and the spec's `version`
    advances."

    Design: Corner/validations/decide_custom_spec_with_cert_succeeds
    """
    spec = create_custom_spec(spec_code="S-V14", cleanliness_grade="FOOD", per_pack_cost=0.90)
    issue_certificate("PACKAGING_SPEC", spec["id"], "FOOD")
    decided = validate_success(
        api.decide_packaging_spec(spec["id"], create_spec_decide_payload("APPROVED"), _MANAGER),
        200,
    )
    assert decided["status"] == "APPROVED", (
        f"with a valid certificate the approval must succeed, got {decided['status']}"
    )
    assert decided["decided_by_user_id"] == "test-manager-0", (
        f"decided_by_user_id must record the decider's X-User-ID, "
        f"got {decided['decided_by_user_id']!r}"
    )


def test_packaging_engineer_cannot_decide_spec(api):
    """PRD §2.1: "A request whose role is not permitted on the targeted
    endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "`PlantManager` is the final authority on custom packaging
    approval"

    Design: Corner/rbac/packaging_engineer_cannot_decide_spec
    """
    spec = create_custom_spec(spec_code="S-R2", cleanliness_grade="FOOD", per_pack_cost=0.90)
    assert spec["status"] == "PENDING_APPROVAL", (
        f"CUSTOM spec must be born PENDING_APPROVAL, got {spec['status']}"
    )
    res = api.decide_packaging_spec(spec["id"], create_spec_decide_payload("APPROVED"), _PACKAGING)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_order_create_computes_required_material(api):
    """PRD §3.5: "At creation the system computes `required_material_kg`: the
    ordered quantity times the nominal per-part mass times 1.18 (nominal mass
    plus the 18-percent trim allowance), rounded half-up to three decimal
    places."
    PRD §3.5: "an optional `is_prototype_order` flag defaulting to false"
    PRD §3.5: "The order is born with `schedule_status` `QUEUED` and
    `quality_status` `PENDING` — two independent dimensions that move
    separately — with `shots_completed` and `shots_scrapped` at zero and
    `provisional_cost`, `tooling_charge`, and `final_cost` all null."

    Design: Corner/entities/order_create_computes_required_material
    """
    tool = create_tool_production(
        tool_code="T-D2", part_number="P-D2C",
        production_cost=8000.00, rated_lifetime_shots=80000,
    )
    spec = create_stock_spec(spec_code="S-D2C")
    payload = create_production_order_payload(
        tool["id"], spec["id"],
        order_code="O-D2", part_number=tool["part_number"],
        ordered_qty=100, std_machine_rate_per_hour=55.00,
    )
    del payload["is_prototype_order"]  # exercise the documented default
    order = validate_success(api.create_production_order(payload, _SCHEDULER), 201)
    assert_production_order(order)
    # 100 x 0.050 x 1.18 = 5.900 (round-half-up at 3dp)
    assert order["required_material_kg"] == 5.900, (
        f"required_material_kg must be 5.900, got {order['required_material_kg']}"
    )
    assert order["is_prototype_order"] is False, "is_prototype_order must default to false"
    assert order["schedule_status"] == "QUEUED"
    assert order["quality_status"] == "PENDING"


def test_order_create_missing_required_field_returns_invalid_request(api):
    """PRD §2.9: "3. **Request schema** — required fields are present, enum
    values are legal, numeric constraints hold (positive where required,
    non-negative where required), conditional fields are supplied exactly when
    required, and range inversions are absent (`ERR_INVALID_REQUEST`)."
    PRD §3.5: "the positive integer `ordered_qty` of good parts required"

    Omitting ordered_qty is a schema violation rejected with
    ERR_INVALID_REQUEST.

    Design: Corner/entities/order_create_missing_required_field_returns_invalid_request
    """
    tool = create_tool_prototype(tool_code="T-D3", part_number="P-D3")
    spec = create_stock_spec(spec_code="S-D3")
    payload = create_production_order_payload(
        tool["id"], spec["id"],
        order_code="O-D3", part_number=tool["part_number"],
        is_prototype_order=True, std_machine_rate_per_hour=55.00,
    )
    del payload["ordered_qty"]
    res = api.create_production_order(payload, _SCHEDULER)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_prototype_tool_order_constraint_violations(api):
    """PRD §3.5: "If the tool is in `PROTOTYPE`, the order must declare
    `is_prototype_order` as true (otherwise `ERR_PROTOTYPE_ORDER_REQUIRED`),
    and its `ordered_qty` must not exceed the tool's 500-shot prototype limit
    (otherwise `ERR_PROTOTYPE_SHOT_LIMIT_EXCEEDED`)."

    Design: Corner/validations/prototype_tool_order_constraint_violations
    """
    tool = create_tool_prototype(tool_code="T-V8", part_number="P-V8")
    spec = create_stock_spec(spec_code="S-V8")

    res_a = api.create_production_order(
        create_production_order_payload(
            tool["id"], spec["id"],
            order_code="O-V8A", part_number=tool["part_number"],
            ordered_qty=50, is_prototype_order=False,
        ),
        _SCHEDULER,
    )
    validate_error(res_a, ApiErrorId.ERR_PROTOTYPE_ORDER_REQUIRED)

    res_b = api.create_production_order(
        create_production_order_payload(
            tool["id"], spec["id"],
            order_code="O-V8B", part_number=tool["part_number"],
            ordered_qty=600, is_prototype_order=True,
        ),
        _SCHEDULER,
    )
    validate_error(res_b, ApiErrorId.ERR_PROTOTYPE_SHOT_LIMIT_EXCEEDED)
