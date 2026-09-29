"""The fixed evaluation order: auth, then existence, then schema, then the business ladder."""
from test_helpers import (
    api_client, validate_error, validate_paginated, ApiErrorId, factories,
    setup_base, create_item, create_active_item, item_lifecycle, reprice_item,
    create_change_request, approve_change_request, review_change_request,
    read_item, read_facility, read_department, read_change_request, set_clock,
    make_manager_headers, make_approver_headers,
    ANALYST, APPROVER, COMPLIANCE, NON_EXISTENT_UUID,
    ANALYST_USER_ID, APPROVER_USER_ID, MANAGER_USER_ID, MANAGER2_USER_ID,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-0001",
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

ITEM = dict(
    cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
    code_type="CPT", code_value="93458", cost_basis_cents=100000,
    medicare_rate_cents=50000, market_p75_cents=900000,
    effective_from="2026-09-01T00:00:00Z",
)


def test_one_bad_body_returns_four_errors_depending_only_on_the_caller():
    """PRD §2.9: "1. Header presence and role legality — `ERR_UNAUTHENTICATED` (401)."
    PRD §2.9: "3. Department scope for a `DepartmentManager` — `ERR_DEPARTMENT_SCOPE_VIOLATION`
    (403)."
    PRD §2.9: "The full evaluation order for any request is fixed, and the **first** failing check
    determines the returned `error_id` — later checks are never allowed to mask an earlier one:"
    PRD §2.9: "11. Payload schema conformance — `ERR_VALIDATION` (422). This covers required fields
    being present, enum members being legal, integers being non-negative, `quantity` being at least
    1, `justification` being at least 10 characters long"

    Design: Corner/validations/auth_ladder_rejects_unauthenticated_then_role_then_department_scope_before_the_schema_check
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    item = create_active_item(base, **ITEM)
    assert item["gross_charge_cents"] == 240000 and item["version"] == 5

    def payload(justification):
        return factories.create_change_request_payload(
            base["department"]["id"], item["id"], "PRICE_CHANGE",
            justification=justification, proposed_cost_basis_cents=120000,
        )

    short = payload("Cost rose")
    assert len(short["justification"]) == 9, "one character short of the schema minimum"

    validate_error(
        api_client.create_change_request(short, {}),
        ApiErrorId.ERR_UNAUTHENTICATED.value, 401,
    )
    validate_error(
        api_client.create_change_request(short, COMPLIANCE),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403,
    )
    validate_error(
        api_client.create_change_request(short, make_manager_headers(MANAGER2_USER_ID)),
        ApiErrorId.ERR_DEPARTMENT_SCOPE_VIOLATION.value, 403,
    )
    validate_error(
        api_client.create_change_request(short, make_manager_headers(MANAGER_USER_ID)),
        ApiErrorId.ERR_VALIDATION.value, 422,
    )

    accepted = create_change_request(
        base, item["id"], "PRICE_CHANGE",
        justification="Cost basis rose after the vendor contract renewal",
        proposed_cost_basis_cents=120000,
    )
    assert accepted["status"] == "SUBMITTED"
    assert accepted["revision_round"] == 0
    assert accepted["submitted_by_user_id"] == MANAGER_USER_ID
    assert accepted["projected_gross_charge_cents"] == 288000

    assert read_department(base["department"]["id"])["open_request_count"] == 1
    rows, meta = validate_paginated(
        api_client.list_change_requests(ANALYST, {"department_id": base["department"]["id"]})
    )
    assert meta["total_count"] == 1, "the four rejected calls created nothing"
    assert len(rows) == 1


def test_existence_checks_outrank_the_schema_and_resolve_left_to_right():
    """PRD §2.9: "Nested paths are resolved strictly left to right, and the outermost missing segment
    determines the error."
    PRD §2.9: "4. `facility_id`, wherever it appears in a path or body, resolves to a `Facility` —
    `ERR_FACILITY_NOT_FOUND` (404)."
    PRD §2.9: "5. `charge_item_id` in the path resolves — `ERR_CHARGE_ITEM_NOT_FOUND` (404)."
    PRD §2.9: "10. Body foreign keys resolve, checked left to right in this declaration order:
    `department_id`, then `revenue_code_id` or `proposed_revenue_code_id`, then `charge_item_id`, then
    `companion_required_item_id`, then `duplicate_of_item_id`, then `recovery_captured_charge_id` —
    `ERR_REFERENCED_RESOURCE_NOT_FOUND` (404)."

    Design: Corner/validations/existence_outranks_schema_so_an_unknown_facility_or_fk_returns_not_found_left_to_right
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)

    unknown_facility = factories.create_charge_item_payload(
        NON_EXISTENT_UUID, base["department"]["id"], base["revenue_code"]["id"],
        cdm_number="CDM-9001", description="GHOST", code_type="BOGUS",
        cost_basis_cents=-5, medicare_rate_cents=50000, market_p75_cents=900000,
        effective_from="2026-09-01T00:00:00Z",
    )
    validate_error(
        api_client.create_charge_item(unknown_facility, ANALYST),
        ApiErrorId.ERR_FACILITY_NOT_FOUND.value, 404,
    )

    unknown_fks = factories.create_charge_item_payload(
        base["facility"]["id"], NON_EXISTENT_UUID, NON_EXISTENT_UUID,
        cdm_number="CDM-9002", description="GHOST", code_type="BOGUS",
        cost_basis_cents=-5, medicare_rate_cents=50000, market_p75_cents=900000,
        effective_from="2026-09-01T00:00:00Z",
    )
    validate_error(
        api_client.create_charge_item(unknown_fks, ANALYST),
        ApiErrorId.ERR_REFERENCED_RESOURCE_NOT_FOUND.value, 404,
    )

    validate_error(
        api_client.get_department(NON_EXISTENT_UUID, ANALYST),
        ApiErrorId.ERR_GOVERNANCE_RESOURCE_NOT_FOUND.value, 404,
    )
    validate_error(
        api_client.get_charge_item(NON_EXISTENT_UUID, ANALYST),
        ApiErrorId.ERR_CHARGE_ITEM_NOT_FOUND.value, 404,
    )
    validate_error(
        api_client.reprice_charge_item(NON_EXISTENT_UUID, ANALYST),
        ApiErrorId.ERR_CHARGE_ITEM_NOT_FOUND.value, 404,
    )

    facility = read_facility(base["facility"]["id"])
    assert facility["active_item_count"] == 0
    assert facility["version"] == 1, "five refusals wrote nothing"
    rows, meta = validate_paginated(
        api_client.list_charge_items(ANALYST, {"facility_id": base["facility"]["id"]})
    )
    assert meta["total_count"] == 0 and rows == []


def test_approval_walks_occ_then_segregation_then_review_before_succeeding():
    """PRD §3.5: "Its preconditions are evaluated in this order. First — after the generic state
    admissibility check and before every business rule — the supplied `expected_charge_item_version`
    must equal the live `ChargeItem.version`, otherwise `ERR_STALE_ITEM_VERSION` (HTTP 412). Second,
    `X-User-ID` must differ from `submitted_by_user_id` *and* from `reviewed_by_user_id`
    (`ERR_SEGREGATION_OF_DUTIES`). Third, `reviewed_by_user_id` must not be null — a request cannot
    jump review — otherwise `ERR_REQUEST_NOT_REVIEWED` (409)."
    PRD §2.9: "16. Charge-item stale-version rejection — `ERR_STALE_ITEM_VERSION` (412)."
    PRD §3.5: "For `PRICE_CHANGE` and `NEW_ITEM`, the target item's `price_status` moves to
    `REPRICE_PENDING` and `ChargeItem.version` advances by 1; `pinned_charge_item_version` is set to
    the *post-bump* version so that the later implementation can match it."

    Design: Corner/validations/approve_cascade_runs_occ_then_segregation_then_not_reviewed_then_succeeds
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    item = create_item(base, **ITEM)
    priced = reprice_item(item["id"])
    stale_token = priced["version"]
    assert stale_token == 2, "the reprice response is three writes behind the live item"
    item_lifecycle(item["id"], "SUBMIT_FOR_REVIEW")
    item_lifecycle(item["id"], "APPROVE")
    activated = item_lifecycle(item["id"], "ACTIVATE")
    live_token = activated["version"]
    assert live_token == 5

    request = create_change_request(
        base, item["id"], "PRICE_CHANGE",
        justification="Cost basis rose after the vendor contract renewal",
        proposed_cost_basis_cents=120000,
    )
    assert request["projected_gross_charge_cents"] == 288000
    assert request["projected_markup_ratio_bp"] == 24000

    reviewed = review_change_request(request["id"], ANALYST,
                                    decision_note="Costs verified against the invoice")
    assert reviewed["status"] == "UNDER_REVIEW"

    validate_error(
        api_client.approve_change_request(
            request["id"], {"expected_charge_item_version": stale_token}, APPROVER
        ),
        ApiErrorId.ERR_STALE_ITEM_VERSION.value, 412,
    )

    validate_error(
        api_client.approve_change_request(
            request["id"], {"expected_charge_item_version": live_token},
            make_approver_headers(ANALYST_USER_ID),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409,
    )

    approved = approve_change_request(request["id"], live_token, APPROVER)
    assert approved["status"] == "APPROVED"
    assert approved["pinned_charge_item_version"] == 6

    stored = read_change_request(request["id"])
    assert stored["approved_by_user_id"] == APPROVER_USER_ID
    assert stored["reviewed_by_user_id"] == ANALYST_USER_ID

    after = read_item(item["id"])
    assert after["price_status"] == "REPRICE_PENDING"
    assert after["version"] == 6
    assert after["gross_charge_cents"] == 240000, "approval does not reprice"
