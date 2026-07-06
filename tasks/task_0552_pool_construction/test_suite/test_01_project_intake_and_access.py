"""Project intake, foreign-key integrity, body validation, and access control."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
    assert_pool_project, assert_ledger_conservation,
    create_pool_project_payload, create_design_plan_payload, create_subcontractor_payload,
    create_crew_assignment_payload,
    TEST_USERS, make_subcontractor_headers,
    setup_started_gate_two_subs_one_booked,
)


def test_project_create_initializes_ledger_and_lifecycle(api, builder_headers):
    """PRD §3.1: "At creation the project's construction_status is NOT_STARTED and its version is 1."
    PRD §3.1: "The ledger is seeded so that contract_amount_cents equals the signed
    contract_price_cents, amount_disbursed_cents and retainage_held_cents are both zero, and
    amount_remaining_cents therefore equals the full contract_price_cents."
    PRD §3.1: "With no design filed yet the project's design_status is NO_DESIGN, and with no
    failed gates, no open safety or major punch items, and a non-negative balance, its posture is OPEN."

    Design: Corner/entities/project_create_returns_initialized_fields
    """
    res = api.create_pool_project(create_pool_project_payload(contract_price_cents=500000), builder_headers)
    project = validate_success(res, 201)
    assert_pool_project(project)
    assert project["construction_status"] == "NOT_STARTED"
    assert project["version"] == 1
    assert project["posture"] == "OPEN"
    assert project["design_status"] == "NO_DESIGN"
    assert project["contract_amount_cents"] == 500000
    assert project["amount_disbursed_cents"] == 0
    assert project["retainage_held_cents"] == 0
    assert project["amount_remaining_cents"] == 500000
    assert_ledger_conservation(project)


def test_get_unknown_project_returns_not_found(api, builder_headers):
    """PRD §2.6: "every id, whether a path id or a foreign-key id in the request body, resolves to
    an existing resource. Ids are resolved left-to-right in the order they appear, and the first
    unresolved id yields ERR_NOT_FOUND (404)."

    Design: Corner/entities/project_get_not_found
    """
    res = api.get_pool_project(NON_EXISTENT_UUID, builder_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_create_project_missing_contract_price_rejected(api, builder_headers):
    """PRD §2.6: "required body fields are present, enum-typed fields carry a legal value, numeric
    fields that must be positive are greater than zero, else ERR_VALIDATION (422)."
    PRD §3.1: "the signed base contract_price_cents (which must be greater than zero)".

    Design: Corner/entities/project_create_missing_contract_price_returns_invalid
    """
    payload = create_pool_project_payload()
    del payload["contract_price_cents"]
    res = api.create_pool_project(payload, builder_headers)
    validate_error(res, ApiErrorId.ERR_VALIDATION)


def test_create_subcontractor_illegal_trade_rejected(api, builder_headers):
    """PRD §2.6: "required body fields are present, enum-typed fields carry a legal value, numeric
    fields that must be positive are greater than zero, else ERR_VALIDATION (422)."
    PRD §3.5: "a trade — one of EXCAVATOR, STEEL, PLUMBER, GUNITE, PLASTER, or GENERAL."

    Design: Corner/entities/subcontractor_invalid_trade_enum_returns_invalid
    """
    res = api.create_subcontractor(create_subcontractor_payload(company_name="S", trade="WELDER"),
                                   builder_headers)
    validate_error(res, ApiErrorId.ERR_VALIDATION)


def test_create_design_for_unknown_project_returns_not_found(api, designer_headers):
    """PRD §2.6: "every id, whether a path id or a foreign-key id in the request body, resolves to
    an existing resource. Ids are resolved left-to-right in the order they appear, and the first
    unresolved id yields ERR_NOT_FOUND (404)."

    Design: Corner/entities/design_create_unknown_project_fk_returns_not_found
    """
    res = api.create_design_plan(create_design_plan_payload(NON_EXISTENT_UUID), designer_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_designer_cannot_create_project(api, designer_headers):
    """PRD §2.1: "A request that authenticates successfully but whose role is not permitted to
    perform the requested operation — or that fails an ownership check described below — is
    rejected with ERR_FORBIDDEN (HTTP 403)." Per PRD §4, creating a pool project is a BuilderPM
    operation.

    Design: Corner/rbac/designer_cannot_create_project_forbidden
    """
    res = api.create_pool_project(create_pool_project_payload(), designer_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "A request whose X-User-Role header is missing or does not name one of these five
    roles is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    headers_without_role = {"X-User-ID": "anon"}
    res = api.create_pool_project(create_pool_project_payload(), headers_without_role)
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


def test_subcontractor_cannot_complete_another_subs_assignment(api):
    """PRD §2.1: "a Subcontractor acting on a booking whose subcontractor_id is not its own
    X-User-ID is rejected with ERR_FORBIDDEN."

    Design: Corner/rbac/subcontractor_cannot_complete_others_assignment_forbidden
    """
    project, gate, sub1, sub2, assignment1 = setup_started_gate_two_subs_one_booked()
    # sub2 tries to complete sub1's booking.
    res = api.transition_crew_assignment(assignment1["id"], {"action": "COMPLETE"},
                                         make_subcontractor_headers(sub2["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
