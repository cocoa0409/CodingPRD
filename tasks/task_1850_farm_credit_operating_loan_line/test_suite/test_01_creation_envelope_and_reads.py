"""Creation defaults, response envelope, not-found reads, request-shape errors,
pagination, and immediate consistency (PRD sections 2.2, 2.3, 2.6, 2.7, 3.1-3.4).
"""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS, api_client, assert_association,
    assert_collateral, assert_loan, create_association_payload,
    create_borrower_payload, create_collateral_payload, create_draft_loan,
    create_loan_payload, disburse_draw, get_success_data, is_valid_uuid,
    setup_active_loan, validate_error, validate_paginated, validate_success,
)

BOARD = TEST_USERS["board_headers"]
OFFICER = TEST_USERS["loan_officer_headers"]


def test_association_create_returns_envelope_and_system_defaults(api):
    """PRD section 3.1: "The new association starts with `review_index` 0 and an
    empty `active_disaster_declarations` list." PRD section 2.6: "The `id` is a
    server-minted UUID with no type prefix." PRD section 2.2: "The `response_type`
    is either "object" for a single resource or "array" for a list of resources."

    Design: Corner/entities/association_create_returns_envelope_and_system_defaults
    """
    resp = api.create_association(
        create_association_payload(name="Blackhawk FCS", charter_number="CH-1850"),
        BOARD)
    assert resp.json()["response_type"] == "object"
    data = validate_success(resp, 201)
    assert_association(data)
    assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
    assert data["review_index"] == 0, "association starts with review_index 0"
    assert data["active_disaster_declarations"] == [], "disaster list starts empty"


def test_borrower_missing_required_field_returns_invalid_request(api):
    """PRD section 2.7: "4. **Request shape.** Required fields are present, enum
    values are in range, amounts are positive integers, window fields start before
    they end, and an approved commitment is positive and no more than the requested
    commitment — `ERR_INVALID_REQUEST`."

    Design: Corner/entities/borrower_missing_required_field_returns_invalid_request
    """
    assoc = get_success_data(api.create_association(create_association_payload(), BOARD))
    payload = {"association_id": assoc["id"], "legal_name": "No County Farms",
               "tax_id": "41-9"}  # county omitted
    resp = api.create_borrower(payload, OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    data, meta = validate_paginated(
        api.list_borrowers(OFFICER, {"association_id": assoc["id"]}))
    assert meta["total_count"] == 0 and data == [], \
        "a rejected create must not persist a borrower row"


def test_collateral_default_prior_lien_applied(api):
    """PRD section 3.4: "A `LoanOfficer` pledges collateral to a loan by naming the
    `loan_account_id`, the `collateral_type` — `CHATTEL_CROP`, `EQUIPMENT`, or
    `REAL_ESTATE`, which selects the advance rate used in Section 3.3 — a free-text
    `description`, the current `appraised_value_cents`, and optionally
    `prior_lien_cents`, which defaults to 0 when omitted." PRD section 3.4: "The
    item enters `PLEDGED` with `perfection_state` `UNPERFECTED`, and unperfected
    collateral contributes nothing to the borrowing base until a filing perfects it."

    Design: Corner/entities/collateral_default_prior_lien_applied
    """
    ctx = create_draft_loan()
    resp = api.create_collateral(
        create_collateral_payload(loan_account_id=ctx["loan"]["id"],
                                  collateral_type="EQUIPMENT", description="Planter",
                                  appraised_value_cents=4_000_000),
        OFFICER)
    data = validate_success(resp, 201)
    assert_collateral(data)
    assert data["prior_lien_cents"] == 0, "omitted prior_lien_cents defaults to 0"
    assert data["status"] == "PLEDGED"
    assert data["perfection_state"] == "UNPERFECTED"


def test_loan_get_unknown_id_returns_not_found(api):
    """PRD section 2.7: "5. **Existence.** Path identifiers and body-supplied
    foreign keys — `loan_account_id`, `borrower_id`, `collateral_id`, `policy_id`,
    `association_id` — resolve to existing records, validated left to right —
    `ERR_NOT_FOUND`."

    Design: Corner/entities/loan_get_unknown_id_returns_not_found
    """
    resp = api.get_loan(NON_EXISTENT_UUID, OFFICER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_collateral_invalid_enum_value_returns_invalid_request(api):
    """PRD section 3.4: "A `LoanOfficer` pledges collateral to a loan by naming the
    `loan_account_id`, the `collateral_type` — `CHATTEL_CROP`, `EQUIPMENT`, or
    `REAL_ESTATE`, which selects the advance rate used in Section 3.3". PRD section
    2.7: "4. **Request shape.** Required fields are present, enum values are in
    range, amounts are positive integers, window fields start before they end, and
    an approved commitment is positive and no more than the requested commitment —
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/collateral_invalid_enum_value_returns_invalid_request
    """
    ctx = create_draft_loan()
    resp = api.create_collateral(
        create_collateral_payload(loan_account_id=ctx["loan"]["id"],
                                  collateral_type="GOLD", description="Gold bars",
                                  appraised_value_cents=100),
        OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_loan_create_initial_state(api):
    """PRD section 3.2: "The new loan enters `DRAFT` with `payment_posture`
    `CURRENT`, both balances — `outstanding_principal_cents` and
    `accrued_interest_cents` — at 0, `approved_commitment_cents` still null, and
    its `association_id` denormalized from the borrower record at creation so the
    loan's association never drifts from its owner's."

    Design: Corner/state_machines/loan_create_initial_state
    """
    assoc = get_success_data(api.create_association(create_association_payload(), BOARD))
    bor = get_success_data(api.create_borrower(
        create_borrower_payload(association_id=assoc["id"]), OFFICER))
    resp = api.create_loan(create_loan_payload(borrower_id=bor["id"]), OFFICER)
    data = validate_success(resp, 201)
    assert_loan(data)
    assert data["status"] == "DRAFT"
    assert data["payment_posture"] == "CURRENT"
    assert data["outstanding_principal_cents"] == 0
    assert data["accrued_interest_cents"] == 0
    assert data["approved_commitment_cents"] is None
    assert data["association_id"] == assoc["id"], \
        "association denormalized from the borrower at creation"


def test_post_then_get_immediate_visibility(api):
    """PRD section 2.8: "Consistency is immediate: every mutation's effects are
    visible in that mutation's own response." PRD section 2.6: "`created_at` is
    fixed at creation and `updated_at` refreshes on every mutation of that
    resource."

    Design: Corner/consistency_model/post_then_get_immediate_visibility
    """
    ctx = create_draft_loan()
    col = get_success_data(api.create_collateral(
        create_collateral_payload(loan_account_id=ctx["loan"]["id"],
                                  collateral_type="EQUIPMENT", description="Planter",
                                  appraised_value_cents=4_000_000),
        OFFICER))
    data = validate_success(api.get_collateral(col["id"], OFFICER), 200)
    assert_collateral(data)
    assert data["appraised_value_cents"] == 4_000_000, \
        "created collateral is fully visible to a same-instant GET"
    assert data["created_at"] == data["updated_at"], \
        "at creation the two timestamps coincide — no async reconciliation lag"


def test_draw_list_pagination_and_status_filter(api):
    """PRD section 2.3: "List endpoints paginate with two query parameters:
    `limit` (default 10, minimum 1, maximum 100) and `offset` (default 0)." PRD
    section 2.3: "`association_id`, `borrower_id`, `loan_account_id`,
    `collateral_id`, `policy_id`, `assigned_loan_id`, `collateral_type`, and
    `status` appear as filters on the lists that own them, alongside the
    pagination parameters."

    Design: Corner/entities/draw_list_pagination_and_status_filter
    """
    ctx = setup_active_loan(collateral_type="REAL_ESTATE",
                            appraised_value_cents=60_000_000,
                            projected_revenue_cents=80_000_000,
                            projected_expenses_cents=50_000_000)
    loan_id = ctx["loan"]["id"]
    d1 = get_success_data(api.create_draw_request(
        {"loan_account_id": loan_id, "amount_cents": 100_000, "purpose": "FUEL"},
        OFFICER))
    get_success_data(api.approve_draw_request(d1["id"], OFFICER))
    d2 = get_success_data(api.create_draw_request(
        {"loan_account_id": loan_id, "amount_cents": 200_000, "purpose": "SEED"},
        OFFICER))
    get_success_data(api.deny_draw_request(d2["id"], OFFICER, reason="purpose not covered"))
    get_success_data(api.create_draw_request(
        {"loan_account_id": loan_id, "amount_cents": 300_000, "purpose": "LABOR"},
        OFFICER))

    data, meta = validate_paginated(
        api.list_draw_requests(OFFICER, {"loan_account_id": loan_id,
                                         "limit": 2, "offset": 0}))
    assert meta["total_count"] == 3 and meta["has_more"] is True
    assert len(data) == 2, "limit=2 returns exactly one page of two"

    data, meta = validate_paginated(
        api.list_draw_requests(OFFICER, {"loan_account_id": loan_id,
                                         "status": "DENIED"}))
    assert meta["total_count"] == 1 and meta["has_more"] is False
    assert len(data) == 1 and data[0]["id"] == d2["id"], \
        "the status filter selects only matching draws"
