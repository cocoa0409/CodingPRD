"""Security and protocol cross-cutting: RBAC denials, segregation of duties,
auth header enforcement, per-entity 404s, and the response envelope."""
from test_helpers import (
    ApiErrorId,
    build_user_headers,
    complete_line_cleaning,
    create_active_contract,
    create_gluten_test_payload,
    create_line,
    create_line_payload,
    create_recipe_payload,
    create_recipe_draft,
    create_zone,
    get_line,
    make_qa_manager_headers,
    receive_lot,
    record_gluten_test,
    record_pest_inspection,
    setup_scheduled_run,
    start_line_cleaning,
    submit_lot_labs,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
PROC = TEST_USERS["procurement_manager_headers"]
TECH = TEST_USERS["qa_technician_headers"]
QAM = TEST_USERS["qa_manager_headers"]
OP = TEST_USERS["production_operator_headers"]
CLERK = TEST_USERS["warehouse_clerk_headers"]


def test_rbac_role_denial_matrix(api):
    """PRD: "A request whose authenticated role is not in the endpoint's
    permitted role list is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/rbac_role_denial_matrix
    """
    contract = create_active_contract(contract_code="C-RB")
    lot = receive_lot(contract["id"], 100.0)
    line = create_line("L-RB")

    e1 = api.create_recipe(create_recipe_payload(recipe_name="Forbidden"), OP)
    validate_error(e1, ApiErrorId.ERR_FORBIDDEN)

    e2 = api.create_semolina_lot(
        {"contract_id": contract["id"], "delivery_date": "2026-08-01",
         "received_weight_kg": 50.0, "cert_protein_pct": 13.0,
         "cert_moisture_pct": 14.5, "cert_gluten_index": 80,
         "cert_falling_number_s": 300},
        PM,
    )
    validate_error(e2, ApiErrorId.ERR_FORBIDDEN)

    e3 = api.accept_lot(lot["id"], TECH)
    validate_error(e3, ApiErrorId.ERR_FORBIDDEN)

    e4 = api.create_production_run(
        {"recipe_id": lot["id"], "line_id": line["id"],
         "semolina_lot_id": lot["id"], "planned_input_kg": 10.0,
         "scheduled_start": "2026-08-10T00:00:00Z",
         "scheduled_end": "2026-08-11T00:00:00Z",
         "expected_line_version": line["version"]},
        CLERK,
    )
    validate_error(e4, ApiErrorId.ERR_FORBIDDEN)

    e5 = api.start_line_cleaning(line["id"], QAM)
    validate_error(e5, ApiErrorId.ERR_FORBIDDEN)

    e6 = api.create_gluten_test(
        {"test_type": "LINE_SWAB", "line_id": line["id"], "result": "PASS"}, PROC)
    validate_error(e6, ApiErrorId.ERR_FORBIDDEN)

    # No side effects from any rejected call.
    assert get_line(line["id"])["version"] == 1
    assert validate_success(api.list_recipes(PM)) == []
    assert validate_success(api.list_production_runs(OP)) == []
    assert validate_success(api.list_gluten_tests(TECH)) == []


def test_sod_recorder_cannot_verify_and_creator_cannot_approve(api):
    """PRD: "Four actions enforce that the deciding user differs from the
    originating user, and all four reject with `ERR_SOD_VIOLATION` (HTTP 403)
    when breached."
    PRD: "Verifying a gluten test requires the verifier's `X-User-ID` to differ
    from the test's `recorded_by_user_id`; the same rule governs verifying a
    pest inspection. Approving a recipe requires the approver to differ from
    the recipe's `created_by_user_id`, and accepting a semolina lot requires
    the acceptor to differ from the lot's `created_by_user_id` — the receiving
    user's identity, captured at goods receipt."

    Design: Corner/rbac/sod_recorder_cannot_verify_and_creator_cannot_approve
    """
    contract = create_active_contract(contract_code="C-SOD")
    lot = receive_lot(contract["id"], 100.0)  # received by proc-1
    submit_lot_labs(lot["id"])
    recipe = create_recipe_draft(recipe_name="SOD Recipe")  # created by pm-1
    zone = create_zone("Z-SOD", "CONVENTIONAL", 5)
    insp = record_pest_inspection(zone["id"], "MINOR")  # recorded by tech-1
    line = create_line("L-SOD")
    start_line_cleaning(line["id"])
    complete_line_cleaning(line["id"])
    swab = record_gluten_test(result="PASS", line_id=line["id"])  # tech-1

    e1 = api.accept_lot(lot["id"], make_qa_manager_headers("proc-1"))
    validate_error(e1, ApiErrorId.ERR_SOD_VIOLATION)

    e2 = api.approve_recipe(recipe["id"], make_qa_manager_headers("pm-1"))
    validate_error(e2, ApiErrorId.ERR_SOD_VIOLATION)

    e3 = api.verify_pest_inspection(insp["id"], make_qa_manager_headers("tech-1"))
    validate_error(e3, ApiErrorId.ERR_SOD_VIOLATION)

    e4 = api.verify_gluten_test(swab["id"], make_qa_manager_headers("tech-1"))
    validate_error(e4, ApiErrorId.ERR_SOD_VIOLATION)

    assert validate_success(api.get_semolina_lot(lot["id"], PM))["status"] == "QUARANTINED"
    assert validate_success(api.get_recipe(recipe["id"], PM))["status"] == "DRAFT"
    assert validate_success(api.get_pest_inspection(insp["id"], PM))["status"] == "RECORDED"
    assert validate_success(api.get_gluten_test(swab["id"], PM))["status"] == "RECORDED"


def test_missing_auth_header_rejected(api):
    """PRD: "A request missing either header, or presenting a role outside the
    six declared roles, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 401)."

    Design: Corner/validations/missing_auth_header_rejected
    """
    payload = create_recipe_payload(recipe_name="NoAuth")

    no_headers = api.create_recipe(payload, {})
    validate_error(no_headers, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    bad_role = api.create_recipe(payload, build_user_headers("someone", "Superuser"))
    validate_error(bad_role, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_resource_not_found_per_entity(api):
    """PRD: "A missing resource surfaces as the entity-specific 404 —
    `ERR_CONTRACT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_RECIPE_NOT_FOUND`,
    `ERR_LINE_NOT_FOUND`, `ERR_DIE_NOT_FOUND`, `ERR_RUN_NOT_FOUND`,
    `ERR_DRYING_SESSION_NOT_FOUND`, `ERR_PACKAGING_JOB_NOT_FOUND`,
    `ERR_ZONE_NOT_FOUND`, `ERR_GOODS_LOT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`,
    or `ERR_GLUTEN_TEST_NOT_FOUND` — rather than a generic error."

    Design: Corner/entities/resource_not_found_per_entity
    """
    cases = [
        (api.get_recipe, "11111111-1111-4111-8111-111111111111", ApiErrorId.ERR_RECIPE_NOT_FOUND),
        (api.get_production_run, "22222222-2222-4222-8222-222222222222", ApiErrorId.ERR_RUN_NOT_FOUND),
        (api.get_warehouse_zone, "33333333-3333-4333-8333-333333333333", ApiErrorId.ERR_ZONE_NOT_FOUND),
        (api.get_finished_goods_lot, "44444444-4444-4444-8444-444444444444", ApiErrorId.ERR_GOODS_LOT_NOT_FOUND),
        (api.get_contract, "55555555-5555-4555-8555-555555555555", ApiErrorId.ERR_CONTRACT_NOT_FOUND),
        (api.get_semolina_lot, "66666666-6666-4666-8666-666666666666", ApiErrorId.ERR_LOT_NOT_FOUND),
        (api.get_production_line, "77777777-7777-4777-8777-777777777777", ApiErrorId.ERR_LINE_NOT_FOUND),
        (api.get_extrusion_die, "88888888-8888-4888-8888-888888888888", ApiErrorId.ERR_DIE_NOT_FOUND),
        (api.get_drying_session, "99999999-9999-4999-8999-999999999999", ApiErrorId.ERR_DRYING_SESSION_NOT_FOUND),
        (api.get_packaging_job, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", ApiErrorId.ERR_PACKAGING_JOB_NOT_FOUND),
        (api.get_pest_inspection, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", ApiErrorId.ERR_INSPECTION_NOT_FOUND),
        (api.get_gluten_test, "cccccccc-cccc-4ccc-8ccc-cccccccccccc", ApiErrorId.ERR_GLUTEN_TEST_NOT_FOUND),
    ]
    for get_fn, missing_id, expected in cases:
        resp = get_fn(missing_id, PM)
        validate_error(resp, expected)


def test_response_envelope_success_and_error_shape(api):
    """PRD: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."
    PRD: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."
    PRD: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/endpoints/response_envelope_success_and_error_shape
    """
    created = api.create_production_line(create_line_payload("L-ENV"), PM)
    body = created.json()
    assert created.status_code == 201
    assert body["response_type"] == "object"
    assert body["data"]["id"]
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["meta"]["api_request_timestamp"]

    fetched = api.get_production_line(body["data"]["id"], CLERK).json()
    assert fetched["response_type"] == "object"
    assert fetched["data"]["line_name"] == "L-ENV"

    error = validate_error(api.create_production_line({}, PM),
                           ApiErrorId.ERR_INVALID_REQUEST)
    assert error["error_id"] == "ERR_INVALID_REQUEST"
    assert error["message"].strip(), "error message must be non-empty"


def test_gluten_test_polymorphic_subject_constraints(api):
    """PRD: "The subject is polymorphic and exclusive: a `LINE_SWAB` requires
    `line_id` and forbids `run_id`; a `PRODUCT_TEST` requires `run_id` and
    forbids `line_id`."
    PRD: "The test is born `RECORDED` with `recorded_by_user_id` from the
    header."

    Design: Corner/entities/gluten_test_polymorphic_subject_constraints
    """
    sc = setup_scheduled_run(contract_code="C-POLY", planned_input_kg=100.0,
                             with_die=False)

    e1 = api.create_gluten_test(
        {"test_type": "LINE_SWAB", "line_id": sc["line"]["id"],
         "run_id": sc["run"]["id"], "result": "PASS"},
        TECH,
    )
    validate_error(e1, ApiErrorId.ERR_INVALID_REQUEST)

    e2 = api.create_gluten_test(
        create_gluten_test_payload("PRODUCT_TEST", "PASS"), TECH)
    validate_error(e2, ApiErrorId.ERR_INVALID_REQUEST)

    ok = validate_success(api.create_gluten_test(
        {"test_type": "LINE_SWAB", "line_id": sc["line"]["id"], "result": "PASS"},
        TECH), 201)
    assert ok["status"] == "RECORDED"
    assert ok["recorded_by_user_id"] == "tech-1"
    assert ok["test_type"] == "LINE_SWAB"
    assert ok.get("run_id") in (None, ""), "LINE_SWAB carries no run subject"
