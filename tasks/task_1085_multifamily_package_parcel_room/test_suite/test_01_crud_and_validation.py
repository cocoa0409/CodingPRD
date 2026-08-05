"""CRUD, input validation, existence, basic RBAC, and immediate-consistency claims.

Queue B (Corner): entities, validations[auth], rbac[peer], consistency_model instances.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    build_user_headers, NON_EXISTENT_UUID,
    create_property_payload, create_shelf_payload, create_package_payload,
    create_locker_bank_payload, notify_payload, policy_update_payload,
    assert_property, assert_locker,
    TEST_USERS,
    make_resident_headers,
    make_property, make_carrier, make_resident, make_bank, make_locker, log_package,
    get_locker, get_property,
)

PM = TEST_USERS["pm_headers"]
CONCIERGE = TEST_USERS["concierge_headers"]


def test_create_property_applies_policy_defaults(api, pm_headers):
    """PRD §3.1: "A newly created property starts with `occupancy_posture` equal to `OPEN`,
    all computed counts (`occupied_locker_count`, `in_service_locker_count`,
    `uncollected_fee_cents`, `return_staging_count`) at zero, and `version` at 1."
    PRD §3.1: "the full policy block: `overflow_threshold_pct` (default 0.85)".

    Design: Corner/entities/create_property_returns_201_with_policy_defaults
    """
    res = api.create_property(create_property_payload(name="Default Court"), pm_headers)
    prop = validate_success(res, 201)
    assert_property(prop)
    assert prop["occupancy_posture"] == "OPEN"
    assert prop["overflow_threshold_pct"] == 0.85
    assert prop["version"] == 1


def test_get_nonexistent_package_returns_404(api, concierge_headers):
    """PRD §2.10: "the system validates existence left-to-right along the path first, then body
    foreign keys, and rejects at the first identifier that does not resolve — returning the
    specific not-found error for that resource type: `ERR_PROPERTY_NOT_FOUND`,
    `ERR_LOCKER_BANK_NOT_FOUND`, `ERR_LOCKER_NOT_FOUND`, `ERR_SHELF_NOT_FOUND`,
    `ERR_RESIDENT_NOT_FOUND`, `ERR_CARRIER_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, or
    `ERR_RETAIL_RETURN_NOT_FOUND`, each HTTP 404."

    Design: Corner/entities/get_package_not_found_returns_404
    """
    res = api.get_package(NON_EXISTENT_UUID, concierge_headers)
    validate_error(res, "ERR_PACKAGE_NOT_FOUND", expected_status=404)


def test_create_shelf_missing_capacity_rejected(api, pm_headers):
    """PRD §3.1: "Staff-managed `Shelf` zones are created with a `property_id`, a `zone` label,
    a `storage_class`, and a `capacity` that must be strictly greater than zero".
    PRD §2.10: "body well-formedness — required fields present, enums valid, numeric fields
    non-negative, `capacity` greater than 0, `loyalty_discount_pct` at least 0 and strictly
    less than 1, and `overflow_threshold_pct` strictly greater than 0 and at most 1
    (`ERR_VALIDATION`, 400)."

    Design: Corner/entities/create_shelf_missing_required_capacity_returns_invalid_request
    """
    prop = make_property(name="Val Court")
    payload = create_shelf_payload(prop["id"])
    del payload["capacity"]
    res = api.create_shelf(payload, pm_headers)
    validate_error(res, "ERR_VALIDATION", expected_status=400)


def test_create_shelf_zero_capacity_rejected(api, pm_headers):
    """PRD §2.10: "body well-formedness — required fields present, enums valid, numeric fields
    non-negative, `capacity` greater than 0, `loyalty_discount_pct` at least 0 and strictly
    less than 1, and `overflow_threshold_pct` strictly greater than 0 and at most 1
    (`ERR_VALIDATION`, 400)."

    Design: Corner/entities/create_shelf_nonpositive_capacity_returns_invalid_request
    """
    prop = make_property(name="Val Court")
    res = api.create_shelf(create_shelf_payload(prop["id"], capacity=0), pm_headers)
    validate_error(res, "ERR_VALIDATION", expected_status=400)


def test_create_package_bad_resident_fk_returns_404(api, concierge_headers):
    """PRD §2.10: "the system validates existence left-to-right along the path first, then body
    foreign keys, and rejects at the first identifier that does not resolve — returning the
    specific not-found error for that resource type: `ERR_PROPERTY_NOT_FOUND`,
    `ERR_LOCKER_BANK_NOT_FOUND`, `ERR_LOCKER_NOT_FOUND`, `ERR_SHELF_NOT_FOUND`,
    `ERR_RESIDENT_NOT_FOUND`, `ERR_CARRIER_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, or
    `ERR_RETAIL_RETURN_NOT_FOUND`, each HTTP 404."

    Design: Corner/entities/create_package_bad_resident_fk_returns_404
    """
    prop = make_property(name="FK Court")
    carrier = make_carrier(prop["id"])
    payload = create_package_payload(prop["id"], NON_EXISTENT_UUID, carrier["id"],
                                     tracking_number="T-FK")
    res = api.create_package(payload, concierge_headers)
    validate_error(res, "ERR_RESIDENT_NOT_FOUND", expected_status=404)


def test_duplicate_tracking_number_rejected(api, concierge_headers):
    """PRD §3.2: "The `tracking_number` must be unique within the property across all
    non-terminal packages; a collision with any package not yet in `PICKED_UP`, `RETURNED`,
    or `DISPOSED` is rejected with `ERR_DUPLICATE_TRACKING`."

    Design: Corner/entities/duplicate_tracking_number_returns_conflict
    """
    prop = make_property(name="Dup Court")
    carrier = make_carrier(prop["id"])
    resident = make_resident(prop["id"])
    log_package(prop["id"], resident["id"], carrier["id"], tracking_number="T-DUP")
    dup = create_package_payload(prop["id"], resident["id"], carrier["id"],
                                 tracking_number="T-DUP")
    res = api.create_package(dup, concierge_headers)
    validate_error(res, "ERR_DUPLICATE_TRACKING", expected_status=409)


def test_list_packages_returns_array_with_pagination(api, pm_headers):
    """PRD §2.3: "The `meta` object of every list response includes `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/entities/list_packages_filtered_by_resident_reverse_reachability
    """
    prop = make_property(name="List Court")
    carrier = make_carrier(prop["id"])
    resident = make_resident(prop["id"])
    pkg = log_package(prop["id"], resident["id"], carrier["id"], tracking_number="T-1")
    res = api.list_packages(pm_headers, params={"resident_id": resident["id"]})
    data, meta = validate_paginated(res)
    assert any(p["id"] == pkg["id"] for p in data), "listing must contain the logged package"
    assert "total_count" in meta and "has_more" in meta


def test_missing_auth_role_returns_401(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the recognized
    roles, the request is rejected with `ERR_MISSING_AUTH_HEADER` (HTTP 401). This is the
    highest-priority check and is evaluated before any other validation."

    Design: Corner/validations/missing_auth_header_returns_401
    """
    bad = build_user_headers("nobody-1", "NobodyRole")
    res = api.create_property(create_property_payload(name="NoAuth Court"), bad)
    validate_error(res, "ERR_MISSING_AUTH_HEADER", expected_status=401)


def test_resident_cannot_create_locker_bank(api):
    """PRD §2.1: "When a caller presents a recognized role but that role is not authorized for
    the requested operation — or is authorized only as an owner and fails the ownership test
    described below — the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/resident_cannot_create_locker_bank_returns_403
    """
    prop = make_property(name="RBAC Court")
    resident = make_resident(prop["id"])
    res = api.create_locker_bank(
        create_locker_bank_payload(prop["id"]), make_resident_headers(resident["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_concierge_cannot_run_pms_sync(api, concierge_headers):
    """PRD §2.1: "When a caller presents a recognized role but that role is not authorized for
    the requested operation — or is authorized only as an owner and fails the ownership test
    described below — the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/concierge_cannot_run_pms_sync_returns_403
    """
    prop = make_property(name="PMS Court")
    resident = make_resident(prop["id"])
    res = api.pms_sync(resident["id"], {"event_type": "MOVE_OUT"}, concierge_headers)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_notify_side_effects_visible_immediately(api):
    """PRD §3.3: "If a locker was assigned, its `locker_id` is recorded on the package, that
    locker transitions `AVAILABLE → OCCUPIED` with its `current_package_id` set to the package,
    and the package's `storage_mode` becomes `LOCKER`".

    Design: Corner/consistency_model/notify_side_effects_visible_immediately
    """
    prop = make_property(name="Imm Court")
    carrier = make_carrier(prop["id"])
    resident = make_resident(prop["id"])
    bank = make_bank(prop["id"], storage_class="AMBIENT")
    locker = make_locker(bank["id"], size_class="LARGE")
    pkg = log_package(prop["id"], resident["id"], carrier["id"], tracking_number="T-1")
    res = api.notify_package(
        pkg["id"], notify_payload(storage_target="LOCKER", locker_id=locker["id"]), CONCIERGE)
    notified = validate_success(res, 200)
    assert notified["storage_mode"] == "LOCKER"
    assert notified["locker_id"] == locker["id"]
    assert notified["pickup_code"] is not None and len(notified["pickup_code"]) == 6
    locker_after = get_locker(locker["id"])
    assert_locker(locker_after)
    assert locker_after["status"] == "OCCUPIED"
    assert locker_after["current_package_id"] == pkg["id"]


def test_policy_update_with_stale_version_rejected(api, pm_headers):
    """PRD §2.9: "A policy-update request must carry `expected_property_version` as a required
    field whose value is the client's last-observed `Property.version`. If that value does not
    equal the property's current `version`, the update is rejected with
    `ERR_STALE_PROPERTY_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/policy_update_stale_version_returns_412
    """
    prop = make_property(name="OCC Court")
    stale = prop["version"]
    bank = make_bank(prop["id"], storage_class="AMBIENT")
    make_locker(bank["id"], size_class="MEDIUM")  # locker creation bumps Property.version
    res = api.update_property_policy(
        prop["id"], policy_update_payload(stale, holding_fee_daily_cents=200), pm_headers)
    validate_error(res, "ERR_STALE_PROPERTY_VERSION", expected_status=412)


def test_policy_update_with_fresh_version_applies_and_bumps(api, pm_headers):
    """PRD §3.1: "Applying the update writes the provided fields, increments the property's
    `version` by 1, and recomputes `occupancy_posture` using the new threshold."

    Design: Corner/cross_cutting_complexity_layers/policy_update_fresh_version_succeeds_and_bumps
    """
    prop = make_property(name="OCC2 Court")
    current = get_property(prop["id"])
    res = api.update_property_policy(
        prop["id"], policy_update_payload(current["version"], holding_fee_daily_cents=200),
        pm_headers)
    updated = validate_success(res, 200)
    assert updated["holding_fee_daily_cents"] == 200
    assert updated["version"] == current["version"] + 1
