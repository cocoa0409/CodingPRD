"""CRUD defaults, required fields, referential integrity, RBAC, pagination, and
the already-deposited error.

Corner: entities (defaults, required fields, type constraints, not-found,
cross-resort), endpoints (pagination), rbac (forbidden role, ownership, missing
header), errors (already deposited).
"""
from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated,
    validate_error_is_one_of,
    ApiErrorId, NON_EXISTENT_UUID,
    create_resort, create_owner, create_inventory_unit, create_active_contract,
    create_invoice_payload, create_reservation_payload, deposit_exchange_payload,
    create_contract_payload, get_points_account,
    make_owner_headers, TEST_USERS,
)

_RM = TEST_USERS["resort_manager_headers"]


def _list(response):
    body = response.json()
    return body["data"], body.get("meta", {})


# =========================================================================== #
# Corner: entities
# =========================================================================== #
def test_create_resort_applies_governance_defaults(api):
    """PRD §3.1: "`rescission_days`, the statutory cooling-off window measured in days, defaults to 7;
    `borrow_surcharge_pct`, the fraction of borrowed points added as a surcharge,
    defaults to 0.10; `delinquency_grace_days`, the number of days after an
    invoice's due date before it can be marked delinquent, defaults to 30; and
    `foreclosure_threshold_periods`, the number of escalation periods of continuous
    delinquency required before a case may proceed to foreclosure or termination,
    defaults to 2."
    PRD §3.1: "On creation, the resort's `current_use_year` is initialized to 2026".

    Design: Corner/entities/create_resort_returns_201_with_defaults_applied
    """
    resp = api.create_resort(
        {"name": "Defaults R", "points_per_week_base": 1000,
         "annual_fee_cents_per_1000_points": 20000}, _RM)
    data = validate_success(resp, 201)
    assert data["rescission_days"] == 7, f"default rescission_days 7, got {data['rescission_days']}"
    assert data["borrow_surcharge_pct"] == 0.10, \
        f"default borrow_surcharge_pct 0.10, got {data['borrow_surcharge_pct']}"
    assert data["delinquency_grace_days"] == 30, \
        f"default delinquency_grace_days 30, got {data['delinquency_grace_days']}"
    assert data["foreclosure_threshold_periods"] == 2, \
        f"default foreclosure_threshold_periods 2, got {data['foreclosure_threshold_periods']}"
    assert data["current_use_year"] == 2026, \
        f"default current_use_year 2026, got {data['current_use_year']}"
    assert data["version"] == 1, f"new resort version 1, got {data['version']}"


def test_create_owner_missing_full_name_rejected(api):
    """PRD §3.1: "with a `resort_id`, a `full_name`, and an `email`."
    PRD §2.7: "Fifth, well-formedness of the request body, yielding `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_owner_missing_required_field_rejected
    """
    resort = create_resort()
    resp = api.create_owner({"resort_id": resort["id"], "email": "noname@x.com"}, _RM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_inventory_unit_invalid_week_number_rejected(api):
    """PRD §2.7: "`week_number` being between 1 and 52 inclusive".
    PRD §3.1: "the ISO `week_number` of the year it is bookable for (an integer between 1 and 52
    inclusive)".

    Design: Corner/entities/inventory_unit_invalid_week_number_rejected
    """
    resort = create_resort()
    resp = api.create_inventory_unit(
        {"resort_id": resort["id"], "unit_label": "Bad Week", "week_number": 60, "season": "GOLD"}, _RM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_owner_not_found(api):
    """PRD §2.6: "When a request names a path resource that does not exist, the system rejects it with
    `ERR_NOT_FOUND".

    Design: Corner/entities/get_owner_not_found_returns_404
    """
    create_resort()
    resp = api.get_owner(NON_EXISTENT_UUID, _RM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_contract_cross_resort_owner_rejected(api):
    """PRD §2.6: "When a referenced foreign key — an `owner_id`, `inventory_unit_id`, `contract_id`,
    `invoice_id`, `special_assessment_id`, or `fixed_unit_id` — resolves to a real
    resource that nevertheless belongs to a different resort, the request is
    rejected with `ERR_CROSS_RESORT_REFERENCE`. This check runs on contract
    creation, reservation creation, invoice creation, payment creation, and
    resale-transfer creation."

    Design: Corner/entities/contract_create_cross_resort_owner_rejected
    """
    resort1 = create_resort(name="R1")
    resort2 = create_resort(name="R2")
    owner2 = create_owner(resort2["id"], full_name="O2", email="o2@x.com")
    resp = api.create_contract(
        create_contract_payload(resort1["id"], owner2["id"], annual_points_allotment=5000), _RM)
    validate_error(resp, ApiErrorId.ERR_CROSS_RESORT_REFERENCE.value)


# =========================================================================== #
# Corner: endpoints — pagination
# =========================================================================== #
def test_list_invoices_pagination_meta(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return."
    PRD §2.3: "Paginated and non-paginated list-based responses include the following fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/endpoints/list_invoices_pagination_total_count_and_has_more
    """
    resort = create_resort()
    owner = create_owner(resort["id"])
    contract = create_active_contract(resort["id"], owner["id"], annual_points_allotment=10000)
    get_success_data(api.create_invoice(
        create_invoice_payload(contract["id"], 2026, "2026-02-01T00:00:00Z"), _RM))
    get_success_data(api.create_invoice(
        create_invoice_payload(contract["id"], 2027, "2027-02-01T00:00:00Z"), _RM))

    resp = api.list_invoices(_RM, params={"contract_id": contract["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"limit=1 returns 1 item, got {len(data)}"
    assert meta["total_count"] == 2, f"total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"has_more must be true, got {meta['has_more']}"


# =========================================================================== #
# Corner: rbac
# =========================================================================== #
def test_owner_cannot_create_resort_forbidden(api):
    """PRD §2.1: "When the header pair is well-formed but the named role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/owner_cannot_create_resort_forbidden
    """
    headers = make_owner_headers("11111111-1111-4111-8111-111111111111")
    resp = api.create_resort(
        {"name": "Hijack", "points_per_week_base": 1000, "annual_fee_cents_per_1000_points": 20000},
        headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


def test_resale_agent_cannot_escalate_delinquency_forbidden(api):
    """PRD §2.1: "When the header pair is well-formed but the named role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/resale_agent_cannot_escalate_delinquency_forbidden
    """
    # escalate is ComplianceOfficer-only per the §4 routing table.
    from test_helpers import setup_delinquent_case
    resort, owner, contract, invoice, case = setup_delinquent_case(
        resort_overrides={"delinquency_grace_days": 30},
        contract_overrides={"annual_points_allotment": 10000})
    resp = api.escalate_delinquency_case(case["id"], TEST_USERS["resale_agent_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)
    c = get_success_data(api.get_delinquency_case(case["id"], TEST_USERS["compliance_officer_headers"]))
    assert c["status"] == "NOTICE", f"case must stay NOTICE, got {c['status']}"


def test_owner_acting_on_other_owners_reservation_denied(api):
    """PRD §2.1: "ownership checks on any resource that references an owner compare
    that resource's owning `owner_id` to `X-User-ID`."
    PRD §2.1: "When an `Owner` targets a resource that belongs to a contract held by
    a different owner, the request is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/owner_acting_on_other_owners_reservation_denied
    """
    resort = create_resort()
    owner1 = create_owner(resort["id"], full_name="O1", email="o1@x.com")
    owner2 = create_owner(resort["id"], full_name="O2", email="o2@x.com")
    unit = create_inventory_unit(resort["id"], unit_label="Villa Gold", week_number=25, season="GOLD")
    contract1 = create_active_contract(resort["id"], owner1["id"], annual_points_allotment=5000)

    acct = get_points_account(contract1["id"], 2026, owner1["id"])
    h1 = make_owner_headers(owner1["id"])
    resv = get_success_data(api.create_reservation(
        create_reservation_payload(contract1["id"], unit["id"], 2026, acct["version"]), h1))

    # O2 attempts to confirm O1's reservation.
    resp = api.confirm_reservation(resv["id"], make_owner_headers(owner2["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    r = get_success_data(api.get_reservation(resv["id"], h1))
    assert r["status"] == "HELD", f"reservation must stay HELD, got {r['status']}"


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the recognized roles,
    the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    ghost = {"X-User-ID": "ghost-1", "X-User-Role": "Ghost", "Content-Type": "application/json"}
    resp = api.create_resort(
        {"name": "R", "points_per_week_base": 1000, "annual_fee_cents_per_1000_points": 20000}, ghost)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


# =========================================================================== #
# Corner: errors — already deposited / no longer confirmed
# =========================================================================== #
def test_second_deposit_of_already_deposited_reservation_rejected(api):
    """PRD §3.6: "Depositing requires the owning contract to be `ACTIVE`, failing with
    `ERR_CONTRACT_NOT_ACTIVE` otherwise, and requires that the reservation does not
    already have an exchange deposit in `DEPOSITED` or `REDEEMED` status, failing
    with `ERR_ALREADY_DEPOSITED` otherwise."
    PRD §3.6: "Depositing advances the reservation from `CONFIRMED` to `DEPOSITED_TO_EXCHANGE".

    Design: Corner/errors/error_already_deposited_on_second_deposit
    """
    from test_helpers import setup_active_contract_with_unit, create_deposited_reservation
    resort, owner, contract, unit = setup_active_contract_with_unit(
        season="GOLD", week_number=28, contract_overrides={"annual_points_allotment": 5000})
    resv, _deposit = create_deposited_reservation(resort, owner, contract, unit, exchange_network="RCI")
    headers = make_owner_headers(owner["id"])
    # The reservation is now DEPOSITED_TO_EXCHANGE (not CONFIRMED). A second deposit
    # is rejected: either the from-state guard (ERR_INVALID_STATE) or the explicit
    # already-deposited guard (ERR_ALREADY_DEPOSITED) is faithful per the PRD.
    resp = api.deposit_exchange(resv["id"], deposit_exchange_payload("II"), headers)
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_ALREADY_DEPOSITED.value, ApiErrorId.ERR_INVALID_STATE.value])
