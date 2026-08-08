"""Provisioning, CRUD basics, listing, and role-based access control.

Covers corner-design instances from sections: entities, endpoints, rbac.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    build_user_headers, NON_EXISTENT_UUID, TEST_USERS,
    assert_owner, assert_vehicle, assert_scofflaw_case,
    create_owner_payload, create_vehicle_payload, create_violation_payload,
    setup_owner_vehicle_case, create_owner, create_vehicle, open_case, file_violation,
    make_owner_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
EO = TEST_USERS["enforcement_officer_headers"]


def test_register_owner_returns_201_with_all_fields(api):
    """PRD §3.1: "Registering an owner supplies full_name, dmv_customer_id, email,
    and mailing_state (a two-letter state code), and optionally hardship_status,
    which is one of NONE, PENDING, or APPROVED and defaults to NONE when omitted."

    Design: Corner/entities/create_owner_returns_201_all_fields
    """
    payload = create_owner_payload(full_name="Ann Owner", mailing_state="NY")
    owner = validate_success(api.create_owner(payload, ADMIN), 201)
    assert_owner(owner)
    assert owner["full_name"] == "Ann Owner"
    assert owner["mailing_state"] == "NY"
    assert owner["hardship_status"] == "NONE"


def test_get_nonexistent_case_returns_404(api):
    """PRD §3.1: "Requests that name a resource in their path must resolve it or
    fail with the matching not-found error, validated left to right: ERR_OWNER_NOT_FOUND,
    ERR_VEHICLE_NOT_FOUND, ERR_CASE_NOT_FOUND, ERR_VIOLATION_NOT_FOUND"

    Design: Corner/entities/get_nonexistent_case_returns_404
    """
    res = api.get_case(NON_EXISTENT_UUID, EO)
    validate_error(res, "ERR_CASE_NOT_FOUND", expected_status=404)


def test_file_violation_missing_fine_amount_returns_validation(api):
    """PRD §2.9: "Malformed request bodies — a missing required field, a value of the
    wrong type, or an unparseable enum or timestamp — are rejected with ERR_VALIDATION
    (HTTP 400)."

    Design: Corner/entities/create_violation_missing_required_returns_validation
    """
    _, _, case = setup_owner_vehicle_case()
    payload = create_violation_payload()
    del payload["fine_amount_cents"]
    res = api.create_violation(case["id"], payload, EO)
    validate_error(res, "ERR_VALIDATION", expected_status=400)


def test_new_vehicle_hold_flag_defaults_false(api):
    """PRD §3.1: "A vehicle also carries a computed hold_flag, false at creation,
    which the case machinery raises and lowers as registration holds come and go."

    Design: Corner/entities/vehicle_hold_flag_default_false
    """
    owner = create_owner()
    vehicle = validate_success(
        api.create_vehicle(create_vehicle_payload(owner["id"]), ADMIN), 201)
    assert_vehicle(vehicle)
    assert vehicle["hold_flag"] is False


def test_open_case_copies_owner_id_from_vehicle(api):
    """PRD §3.1: "At creation the system copies the vehicle's owner into the case's
    owner_id (this denormalized copy is what later ownership checks read), and
    initializes case_status to COMPLIANT and hold_status to NO_HOLD."

    Design: Corner/entities/case_owner_id_system_copied_from_vehicle
    """
    owner = create_owner()
    vehicle = create_vehicle(owner["id"])
    case = validate_success(
        api.create_case({"vehicle_id": vehicle["id"]}, EO), 201)
    assert_scofflaw_case(case)
    assert case["owner_id"] == owner["id"]
    assert case["case_status"] == "COMPLIANT"


def test_list_violations_filtered_by_case(api):
    """PRD §3.1: "List endpoints support reverse lookups: vehicles by owner_id or
    plate_number; cases by vehicle_id, owner_id, or case_status; violations by
    scofflaw_case_id or status;"

    Design: Corner/endpoints/list_violations_filtered_by_case
    """
    _, _, case = setup_owner_vehicle_case()
    file_violation(case["id"], fine_amount_cents=10000)
    file_violation(case["id"], fine_amount_cents=10000)
    data, meta = validate_paginated(
        api.list_violations(EO, params={"scofflaw_case_id": case["id"]}))
    assert len(data) == 2
    assert all(v["scofflaw_case_id"] == case["id"] for v in data)


def test_pagination_violations_reports_total_and_has_more(api):
    """PRD §2.3: "Every list response echoes limit and offset in meta, alongside
    total_count (the total number of records matching the filter before pagination)
    and has_more (a boolean, true when records remain beyond the current page)."

    Design: Corner/endpoints/pagination_violations_has_more
    """
    _, _, case = setup_owner_vehicle_case()
    file_violation(case["id"], fine_amount_cents=10000)
    file_violation(case["id"], fine_amount_cents=10000)
    data, meta = validate_paginated(api.list_violations(
        EO, params={"scofflaw_case_id": case["id"], "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_owner_cannot_file_violation(api):
    """PRD §3.2: "Only an enforcement officer files a citation, against a named case."
    PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with ERR_UNAUTHORIZED
    (HTTP 403)."

    Design: Corner/rbac/owner_cannot_file_violation_returns_403
    """
    owner, _, case = setup_owner_vehicle_case()
    res = api.create_violation(
        case["id"], create_violation_payload(fine_amount_cents=10000),
        make_owner_headers(owner["id"]))
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_owner_paying_another_owners_case_rejected(api):
    """PRD §2.1: "an owner may only file or withdraw disputes, make payments, open
    payment plans, request hardship waivers, and pay release fees on cases whose
    owner_id equals their own X-User-ID. An owner acting on a case they do not own
    is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/owner_pays_other_owners_case_returns_403
    """
    owner1, _, case = setup_owner_vehicle_case()
    owner2 = create_owner()
    file_violation(case["id"], fine_amount_cents=10000)
    res = api.create_payment(
        case["id"], {"amount_cents": 10000, "method": "CARD"},
        make_owner_headers(owner2["id"]))
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_unknown_role_returns_401(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role is not one of the
    five roles defined below, the request is rejected with ERR_UNAUTHENTICATED
    (HTTP 401)."

    Design: Corner/rbac/unknown_role_returns_401
    """
    ghost = build_user_headers("ghost-1", "Ghost")
    res = api.get_scofflaw_summary(ghost)
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
