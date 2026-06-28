"""Authentication, role-based access control, and part-master CRUD basics.

Covers queue-B corner instances on RBAC peer-role forbidding, missing-auth rejection,
and the part entity's creation / defaults / required-field / enum / listing claims.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    assert_part,
)
import test_helpers.fixtures as fx
import test_helpers.factories as f

PE = TEST_USERS["process_engineer_headers"]
PP = TEST_USERS["production_planner_headers"]
QE = TEST_USERS["quality_engineer_headers"]


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name one
    of the three known roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_rejected
    """
    payload = f.create_part_payload(internal_pn="C-NOAUTH")
    validate_error(api.create_part(payload, {}), ApiErrorId.ERR_UNAUTHENTICATED.value)


# ---------------------------------------------------------------------------
# RBAC peer-role forbidding
# ---------------------------------------------------------------------------

def test_planner_cannot_create_part(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted
    to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."
    PRD §2.1: "A `ProcessEngineer` owns the engineering definition of the shop: part
    master records, vendors, the approved-vendor list, bills of materials, SMT line
    programs, and the authoring, submission, and implementation of engineering change
    orders."

    Design: Corner/rbac/planner_cannot_create_part
    """
    payload = f.create_part_payload(internal_pn="C-RBAC1")
    validate_error(api.create_part(payload, PP), ApiErrorId.ERR_FORBIDDEN.value)


def test_planner_cannot_record_test_result(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted
    to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."
    PRD §2.1: "A `QualityEngineer` owns quality gating: recording test results,
    finalizing test, quarantining lots, approving and rejecting engineering change
    orders, and receiving, triaging, and scrapping field returns."

    Design: Corner/rbac/planner_cannot_record_test_result
    """
    _part, _bom, _prog, _wo, units = fx.setup_at_test_work_order(planned_qty=1,
                                                                received_qty=10,
                                                                unit_cost_cents=10,
                                                                standard_cost_cents=10)
    # A BUILT unit at AT_TEST; ProductionPlanner is not permitted to record results.
    validate_error(api.record_test_result(units[0]["id"], f.test_result_payload("PASS"), PP),
                   ApiErrorId.ERR_FORBIDDEN.value)


# ---------------------------------------------------------------------------
# Part creation, defaults, required fields, enum
# ---------------------------------------------------------------------------

def test_create_part_returns_201_with_zero_rollups(api):
    """PRD §3.1: "A newly created part starts with `total_on_hand_qty` and
    `available_qty` both at zero."
    PRD §2.4: "an integer `version` that begins at 1 and increments by exactly one on
    each mutation of that record."

    Design: Corner/entities/create_part_returns_201_with_all_fields
    """
    payload = f.create_part_payload(internal_pn="C-PART", description="10k res",
                                    package_type="0402", standard_cost_cents=50)
    created = validate_success(api.create_part(payload, PE), expected_status=201)
    assert_part(created)
    assert created["total_on_hand_qty"] == 0, created
    assert created["available_qty"] == 0, created
    assert created["version"] == 1, created


def test_create_part_defaults_rohs_and_conflict_minerals(api):
    """PRD §3.1: "Two compliance flags may be supplied: `is_rohs_required`, which
    defaults to true and indicates that only RoHS-compliant lots may ever be consumed
    for the part, and `contains_conflict_minerals`, which defaults to false and
    indicates that every consumed lot must carry a conflict-minerals declaration."

    Design: Corner/entities/create_part_default_rohs_required_true
    """
    payload = {"internal_pn": "C-DEF", "description": "x", "package_type": "0402",
               "standard_cost_cents": 10}
    created = validate_success(api.create_part(payload, PE), expected_status=201)
    assert created["is_rohs_required"] is True, created
    assert created["contains_conflict_minerals"] is False, created


def test_create_part_missing_standard_cost_rejected(api):
    """PRD §3.1: "a `standard_cost_cents` catalog cost that must be at least zero."
    PRD §2.7: "basic request-shape validation (required fields present, types and
    enums valid) yields `ERR_INVALID_REQUEST` (HTTP 400) when violated".

    Design: Corner/entities/create_part_missing_required_field_rejected
    """
    payload = {"internal_pn": "C-NOSTD", "description": "x", "package_type": "0402"}
    validate_error(api.create_part(payload, PE), ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_part_invalid_package_type_rejected(api):
    """PRD §3.1: "a `package_type` drawn from the footprint families `0402`, `0603`,
    `0805`, `SOT23`, `QFN`, `BGA`, and `THT`".
    PRD §2.7: "basic request-shape validation (required fields present, types and
    enums valid) yields `ERR_INVALID_REQUEST` (HTTP 400) when violated".

    Design: Corner/entities/invalid_package_type_enum_rejected
    """
    payload = f.create_part_payload(internal_pn="C-BADENUM", package_type="DIP99",
                                    standard_cost_cents=10)
    validate_error(api.create_part(payload, PE), ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# Not found
# ---------------------------------------------------------------------------

def test_get_part_not_found(api):
    """PRD §2.7: "The system then resolves path-referenced resources left to right; if
    any resource named in the URL path does not exist, the request fails with
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_part_not_found
    """
    validate_error(api.get_part(NON_EXISTENT_UUID, PE), ApiErrorId.ERR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Listing / pagination envelope
# ---------------------------------------------------------------------------

def test_list_parts_pagination_envelope(api):
    """PRD §2.3: "For every list response, the `meta` object carries the effective
    `limit`, the effective `offset`, the `total_count` of records matching the query
    before pagination, and a `has_more` boolean that is true when records remain beyond
    the current page."

    Design: Corner/entities/list_parts_pagination_envelope
    """
    fx.create_part()
    fx.create_part()
    data, meta = validate_paginated(api.list_parts(PE, params={"limit": 1, "offset": 0}))
    assert len(data) == 1, data
    assert meta["total_count"] >= 2, meta
    assert meta["has_more"] is True, meta
