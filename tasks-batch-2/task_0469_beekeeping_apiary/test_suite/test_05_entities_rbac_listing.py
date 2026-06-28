"""Entity creation/defaults/computed fields, not-found and FK integrity,
append-only immutability, listing/pagination, retrieval, and RBAC (role and
ownership denials, authentication).

Covers the corner-queue entities / endpoints / rbac instances. Each test's
Design tag names its source.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    create_apiary_payload, create_hive_payload,
    create_inspection_payload,
    TEST_USERS, make_apiary_manager_headers, NON_EXISTENT_UUID,
    assert_apiary, assert_inspection_is_append_only,
    create_apiary, create_hive, set_clock,
)

ADMIN = TEST_USERS["platform_admin_headers"]
APIARIST = TEST_USERS["state_apiarist_headers"]
COORDINATOR = TEST_USERS["contract_coordinator_headers"]
MANAGER = TEST_USERS["apiary_manager_headers"]


# ─── Corner / entities ──────────────────────────────────────────────────────
def test_create_apiary_returns_201_with_computed_defaults(api):
    """PRD §3.1: "On creation the yard's `registration_status` is `UNREGISTERED` and
    its `active_colony_count` is zero."
    PRD §4: "Operations that create a new resource return a `201 Created` status
    code"

    Design: Corner/entities/create_apiary_returns_201_with_system_and_default_fields
    """
    set_clock("2026-01-01T00:00:00Z")
    res = api.create_apiary(
        create_apiary_payload(name="Yard1", max_yard_colonies=40), MANAGER)
    apiary = validate_success(res, 201)
    assert_apiary(apiary)
    assert apiary["registration_status"] == "UNREGISTERED"
    assert apiary["active_colony_count"] == 0


def test_create_hive_missing_apiary_id_invalid_request(api):
    """PRD §3.10: "the system finally checks that the request body is well-formed —
    required fields present, field types correct, and enum values drawn from their
    permitted sets ... A violation of any of these is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_hive_missing_required_apiary_id_returns_invalid_request
    """
    res = api.create_hive({"tag": "H1", "brood_frames": 5},
                          make_apiary_manager_headers("anything"))
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_hive_brood_frames_default_zero(api):
    """PRD §3.2: "optionally an initial `brood_frames` count (a non-negative
    integer, defaulting to zero) and a `source_hive_id` may be supplied."

    Design: Corner/entities/create_hive_brood_frames_default_zero
    """
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    res = api.create_hive({"apiary_id": apiary["id"], "tag": "H1"}, headers)
    hive = validate_success(res, 201)
    assert hive["brood_frames"] == 0


def test_hive_create_increments_apiary_active_colony_count(api):
    """PRD §3.2: "On creation `health_status` is `HEALTHY`, `queen_status` is
    `QUEENRIGHT`, `honey_frames` is zero, and the owning apiary's
    `active_colony_count` rises by one."

    Design: Corner/entities/hive_create_increments_apiary_active_colony_count
    """
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    create_hive(apiary["id"], tag="H1", brood_frames=4)

    ap_after = validate_success(api.get_apiary(apiary["id"], headers), 200)
    assert ap_after["active_colony_count"] == 1


def test_get_nonexistent_hive_not_found(api):
    """PRD §2.7: "The system validates the existence of each path identifier in
    strict left-to-right order and rejects the request at the **first** identifier
    that does not resolve, returning `ERR_NOT_FOUND`."

    Design: Corner/entities/get_hive_nonexistent_returns_not_found
    """
    res = api.get_hive(NON_EXISTENT_UUID, make_apiary_manager_headers("anything"))
    validate_error(res, "ERR_NOT_FOUND")


def test_create_hive_unknown_apiary_fk_not_found(api):
    """PRD §2.7: "when a create request carries a foreign key in its body — such as
    `apiary_id`, `hive_id`, `source_hive_id`, `contract_id`, or `lot_id` — and that
    key does not reference an existing resource, the request is rejected with
    `ERR_FK_NOT_FOUND`."

    Design: Corner/entities/create_hive_unknown_apiary_fk_returns_fk_not_found
    """
    res = api.create_hive(
        {"apiary_id": NON_EXISTENT_UUID, "tag": "H1", "brood_frames": 5},
        make_apiary_manager_headers(NON_EXISTENT_UUID))
    validate_error(res, "ERR_FK_NOT_FOUND")


def test_inspection_is_append_only_no_version(api):
    """PRD §2.4: "an `Inspection` and a `Feeding` are immutable, append-only event
    records. Each carries only `id` and `created_at` — neither `updated_at` nor
    `version` is present on these two, because once written they are never modified."

    Design: Corner/entities/inspection_immutable_entity_no_version_field
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    hive = create_hive(apiary["id"], tag="H1", brood_frames=5)

    insp = validate_success(api.create_inspection(
        hive["id"], create_inspection_payload(), headers), 201)
    assert_inspection_is_append_only(insp)
    assert "updated_at" not in insp


# ─── Corner / endpoints (listing + retrieval) ──────────────────────────────
def test_list_hives_paginated_envelope(api):
    """PRD §2.3: "Paginated list-based responses include the following fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/endpoints/list_hives_paginated_returns_envelope_fields
    """
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    for i in range(3):
        create_hive(apiary["id"], tag=f"H{i}", brood_frames=1)

    data, meta = validate_paginated(
        api.list_hives(headers, params={"apiary_id": apiary["id"], "limit": 2,
                                        "offset": 0}))
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert len(data) == 2


def test_get_apiary_returns_stored_entity(api):
    """PRD §2.4: "The `id` is a unique, server-minted identifier formatted as a UUID
    with no type prefix."
    PRD §3.1: "A yard is established by registering an `Apiary`, supplying its
    `name`, the two-letter `state_code`, its `latitude` and `longitude` in decimal
    degrees, and its `max_yard_colonies`."

    Design: Corner/endpoints/get_apiary_returns_stored_entity
    """
    apiary = create_apiary(name="CA Yard", state_code="OR", latitude=44.0,
                           longitude=-123.0, max_yard_colonies=30)
    headers = make_apiary_manager_headers(apiary["id"])
    got = validate_success(api.get_apiary(apiary["id"], headers), 200)
    assert got["id"] == apiary["id"]
    assert got["state_code"] == "OR"
    assert got["max_yard_colonies"] == 30


# ─── Corner / rbac ──────────────────────────────────────────────────────────
def test_contract_coordinator_cannot_create_hive(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/contract_coordinator_cannot_create_hive_forbidden
    """
    apiary = create_apiary()
    res = api.create_hive({"apiary_id": apiary["id"], "tag": "H1", "brood_frames": 5},
                          COORDINATOR)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_apiary_manager_cannot_act_on_other_apiarys_hive(api):
    """PRD §2.1: "for every `ApiaryManager`-initiated mutation on hives,
    inspections, treatments, harvests, honey lots, feedings, and requeen schedules,
    the system verifies that `X-User-ID` equals the `apiary_id` of the apiary that
    owns the target resource; a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/apiary_manager_cannot_act_on_other_apiarys_hive
    """
    a1 = create_apiary(name="A1")
    a2 = create_apiary(name="A2", latitude=38.6, longitude=-121.6)
    hive = create_hive(a1["id"], tag="H1", brood_frames=5)

    # Manager acting as A2 tries to quarantine A1's hive.
    res = api.quarantine_hive(hive["id"], make_apiary_manager_headers(a2["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    res = api.list_apiaries({"X-User-ID": "x", "X-User-Role": "NoSuchRole"})
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_state_apiarist_approve_exclusive_to_role(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/state_apiarist_approve_exclusive_to_role
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary = create_apiary()
    reg = get_success_data(api.create_registration(
        apiary["id"],
        {"registration_number": "CA-001", "effective_date": "2026-01-01T00:00:00Z",
         "expiry_date": "2026-12-31T00:00:00Z"}, APIARIST))

    res = api.approve_registration(apiary["id"], reg["id"], COORDINATOR)
    validate_error(res, "ERR_FORBIDDEN_ROLE")
