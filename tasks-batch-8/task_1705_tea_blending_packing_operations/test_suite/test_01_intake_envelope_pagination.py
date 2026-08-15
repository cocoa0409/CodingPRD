"""Intake basics: creation defaults, response envelope, required-field and
enum shape checks, existence checks, list pagination, record immutability,
initial states, and immediate read-after-write visibility.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_leaf_lot,
    create_certificate_payload,
    create_contract_payload,
    create_flavoring_payload,
    create_leaf_lot_payload,
    create_packaging_line_payload,
    create_recipe_payload,
    create_supplier,
    create_supplier_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

PL = TEST_USERS["procurement_lead_headers"]
GR = TEST_USERS["sensory_grader_headers"]
QA = TEST_USERS["qa_manager_headers"]
BM = TEST_USERS["blend_master_headers"]
PP = TEST_USERS["production_planner_headers"]
AM = TEST_USERS["account_manager_headers"]
CO = TEST_USERS["certification_officer_headers"]


def test_supplier_create_defaults(api):
    """PRD §3.1: "A `ProcurementLead` opens the supply chain by registering
    each supplier under its `name` and `origin_region`; new suppliers start
    `ACTIVE`."
    PRD §2.4: "Ten primary resources — Supplier, LeafLot, Flavoring,
    BlendRecipe, BlendBatch, BatchLotAllocation, PackagingLine,
    ProductionRun, PrivateLabelContract, and CertificateGrant — share a
    standard set of system-managed fields"

    Design: Corner/entities/supplier_create_defaults
    """
    res = api.create_supplier(
        create_supplier_payload(name="Hill Co", origin_region="Munnar"), PL)
    body = res.json()
    data = validate_success(res, 201)
    assert data["status"] == "ACTIVE", "new suppliers start ACTIVE"
    assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int)
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["response_type"] == "object"


def test_success_envelope_shape(api):
    """PRD §2.2: "The `response_type` is either "object" for a single
    resource or "array" for a list of resources."
    PRD §4: "Operations that create a new resource — a supplier, lot,
    flavoring, recipe, batch, line, run, contract, or certificate — or add
    a new record to a sub-collection — a grade assessment, residue test,
    allocation, or flavoring application — return `201 Created`."

    Design: Corner/endpoints/success_envelope_shape
    """
    supplier = create_supplier(name="Env Co")
    res = api.create_leaf_lot(
        create_leaf_lot_payload(supplier["id"], leaf_type="OOLONG"), PL)
    body = res.json()
    data = validate_success(res, 201)
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert body["response_type"] == "object"
    assert_leaf_lot(data)
    assert data["leaf_type"] == "OOLONG"


def test_leaf_lot_missing_required_weight_returns_invalid_request(api):
    """PRD §3.1: "Each lot record carries the sourcing `supplier_id`, a
    `leaf_type` of `BLACK`, `GREEN`, `WHITE`, `OOLONG`, or `HERBAL`, the
    `harvest_date`, the gross received `weight_kg` (strictly positive), the
    contracted `cost_per_kg_cents` (a non-negative integer), and the intake
    `moisture_pct` (greater than zero and at most one hundred)."
    PRD §2.10: "Field shape: required fields present, enums in range,
    scores within 0 to 100, weights and quantities strictly positive,
    residue measurements non-negative — failures reported as
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/leaf_lot_missing_required_weight_returns_invalid_request
    """
    supplier = create_supplier(name="Req Co")
    payload = create_leaf_lot_payload(supplier["id"])
    del payload["weight_kg"]
    res = api.create_leaf_lot(payload, PL)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
    data, meta = validate_paginated(api.list_leaf_lots(QA))
    assert meta["total_count"] == 0, "rejected create must persist nothing"
    assert data == []


def test_leaf_lot_computed_fields_input_ignored(api):
    """PRD §3.1: "Registration stamps `registered_by_user_id` from the
    calling header, initializes `remaining_weight_kg` to the full
    `weight_kg`, sets both `composite_grade` and `latest_residue_verdict`
    to `NONE`, and places the lot in `REGISTERED`."

    Design: Corner/entities/leaf_lot_computed_fields_input_ignored
    """
    supplier = create_supplier(name="Ign Co")
    payload = create_leaf_lot_payload(
        supplier["id"], weight_kg=25.0, moisture_pct=5.0)
    payload["remaining_weight_kg"] = 999.0
    payload["status"] = "RELEASED"
    res = api.create_leaf_lot(payload, PL)
    data = validate_success(res, 201)
    assert data["remaining_weight_kg"] == 25.0, (
        f"server initializes remaining_weight_kg to weight_kg, "
        f"got {data['remaining_weight_kg']}")
    assert data["status"] == "REGISTERED"
    assert data["composite_grade"] == "NONE"
    assert data["latest_residue_verdict"] == "NONE"


def test_create_lot_invalid_enum_returns_invalid_request(api):
    """PRD §3.1: "a `leaf_type` of `BLACK`, `GREEN`, `WHITE`, `OOLONG`, or
    `HERBAL`"
    PRD §2.10: "Field shape: required fields present, enums in range,
    scores within 0 to 100, weights and quantities strictly positive,
    residue measurements non-negative — failures reported as
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_lot_invalid_enum_returns_invalid_request
    """
    supplier = create_supplier(name="Enum Co")
    res = api.create_leaf_lot(
        create_leaf_lot_payload(supplier["id"], leaf_type="PUERH"), PL)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_lot_fk_unknown_supplier_returns_not_found(api):
    """PRD §2.11: "After the path is validated, foreign keys supplied in
    the request body — `supplier_id`, `recipe_id`, `lot_id`, `line_id`,
    `batch_id`, `contract_id`, and `flavoring_id` — are resolved in the
    same manner and produce the same error when they point at nothing."

    Design: Corner/entities/lot_fk_unknown_supplier_returns_not_found
    """
    res = api.create_leaf_lot(
        create_leaf_lot_payload(NON_EXISTENT_UUID), PL)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_batch_not_found_returns_404(api):
    """PRD §2.11: "When a path contains several identifiers, existence is
    validated left to right, and the request is rejected with
    `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not
    resolve to an existing resource."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."

    Design: Corner/entities/batch_not_found_returns_404
    """
    res = api.get_batch(NON_EXISTENT_UUID, BM)
    body = res.json()
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["data"]["message"], str)
    assert len(body["data"]["message"].strip()) > 0


def test_lot_list_pagination_envelope(api):
    """PRD §2.3: "Paginated list responses carry four fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/entities/lot_list_pagination_envelope
    """
    supplier = create_supplier(name="Page Co")
    for i, leaf_type in enumerate(("BLACK", "GREEN", "OOLONG")):
        res = api.create_leaf_lot(
            create_leaf_lot_payload(
                supplier["id"], leaf_type=leaf_type,
                harvest_date=f"2026-02-0{i + 1}"), PL)
        validate_success(res, 201)

    page1, meta1 = validate_paginated(
        api.list_leaf_lots(QA, params={"limit": 2, "offset": 0}))
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert len(page1) == 2
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_leaf_lots(QA, params={"limit": 2, "offset": 2}))
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert len(page2) == 1


def test_grade_assessment_immutable_shape(api):
    """PRD §2.4: "Three record-type resources — GradeAssessment,
    ResidueTest, and FlavoringApplication — are immutable once created."
    PRD §2.4: "They carry only `id` and `created_at`; both `updated_at`
    and `version` are absent from them."

    Design: Corner/entities/grade_assessment_immutable_shape
    """
    supplier = create_supplier(name="Imm Co")
    lot = validate_success(
        api.create_leaf_lot(create_leaf_lot_payload(supplier["id"]), PL), 201)
    res = api.create_grade_assessment(
        lot["id"],
        {"aroma_score": 90, "briskness_score": 88, "appearance_score": 92},
        GR)
    data = validate_success(res, 201)
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert "version" not in data, "record resources carry no version"
    assert "updated_at" not in data, "record resources carry no updated_at"


def test_initial_states_on_create(api):
    """PRD §3.1: "new suppliers start `ACTIVE`." PRD §3.1: "places the lot
    in `REGISTERED`." PRD §3.3: "Flavorings start `ACTIVE`." PRD §3.3:
    "New recipes start in `DRAFT`." PRD §3.4: "The new batch starts in
    `DRAFT`" PRD §3.7: "lines start `ACTIVE`." PRD §3.8: "Contracts start
    in `DRAFT` with `fulfilled_units` at zero." PRD §3.6: "New grants
    start `ACTIVE` with `consumed_volume_kg` at zero."

    Design: Corner/state_machines/initial_states_on_create
    """
    supplier = create_supplier(name="Init Co")
    assert supplier["status"] == "ACTIVE"

    lot = validate_success(
        api.create_leaf_lot(create_leaf_lot_payload(supplier["id"]), PL), 201)
    assert lot["status"] == "REGISTERED"

    flavoring = validate_success(
        api.create_flavoring(
            create_flavoring_payload(name="Lemon", cost_per_kg_cents=2000),
            BM), 201)
    assert flavoring["status"] == "ACTIVE"

    recipe = validate_success(
        api.create_recipe(
            create_recipe_payload(
                name="RI",
                components=[{"leaf_type": "BLACK", "min_grade": "C",
                             "pct": 100.0}]), BM), 201)
    assert recipe["status"] == "DRAFT"
    validate_success(api.activate_recipe(recipe["id"], BM), 200)

    batch = validate_success(
        api.create_batch({"recipe_id": recipe["id"], "target_weight_kg": 10.0},
                         BM), 201)
    assert batch["status"] == "DRAFT"

    line = validate_success(
        api.create_packaging_line(
            create_packaging_line_payload(name="LP-I"), PP), 201)
    assert line["status"] == "ACTIVE"

    contract = validate_success(
        api.create_contract(create_contract_payload(recipe["id"]), AM), 201)
    assert contract["status"] == "DRAFT"
    assert contract["fulfilled_units"] == 0

    cert = validate_success(
        api.create_certificate(
            create_certificate_payload(supplier["id"], total_volume_kg=100.0),
            CO), 201)
    assert cert["status"] == "ACTIVE"
    assert cert["consumed_volume_kg"] == 0


def test_version_increments_and_immediate_visibility(api):
    """PRD §2.4: "`version` (integer): a system-managed counter that
    increments by one on every mutation — including mutations caused by
    the cascades of §2.8, which touch each affected entity in its own
    right."
    PRD §3.2: "The lot adopts the assessment's `composite_grade` as its
    own: a grade of `A`, `B`, or `C` moves it from `REGISTERED` to
    `GRADED`, while a `REJECT` grade moves it straight to `REJECTED`."

    Design: Corner/consistency_model/version_increments_and_immediate_visibility
    """
    supplier = create_supplier(name="Cons Co")
    lot = validate_success(
        api.create_leaf_lot(create_leaf_lot_payload(supplier["id"]), PL), 201)
    v1 = lot["version"]
    assert lot["status"] == "REGISTERED"

    validate_success(
        api.create_grade_assessment(
            lot["id"],
            {"aroma_score": 80, "briskness_score": 80, "appearance_score": 80},
            GR), 201)

    after = validate_success(api.get_leaf_lot(lot["id"], QA), 200)
    assert after["version"] == v1 + 1, (
        f"grading is one mutation: version {v1} -> {after['version']}")
    assert after["composite_grade"] == "B"
    assert after["status"] == "GRADED"
