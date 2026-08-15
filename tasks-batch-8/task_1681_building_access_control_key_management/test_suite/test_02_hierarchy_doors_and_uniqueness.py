"""Key hierarchy rules, door creation rules, and per-building uniqueness."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_access_event,
    assert_timestamp_equals,
    create_access_group,
    create_building,
    create_credential,
    create_key_node,
    create_master_change_chain,
    create_person,
    create_door,
    get_success_data,
    issue_credential,
    access_check,
    set_clock,
    setup_building_with_chain,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["security_admin_headers"]
DESK = TEST_USERS["front_desk_headers"]
OFFICER = TEST_USERS["security_officer_headers"]


def test_key_node_level_skip_and_bad_root_rejected(api):
    """PRD §3.1: "A node may name a `parent_id`; when present, the parent's
    level must be exactly one step above the child's along the chain
    `GRAND_MASTER` → `MASTER` → `SUB_MASTER` → `CHANGE`, and when absent the
    node is a root whose level must be either `GRAND_MASTER` or `MASTER`. Any
    violation of that adjacency or root rule is rejected with
    `ERR_KEY_HIERARCHY_INVALID`."

    Design: Corner/entities/key_node_level_skip_and_bad_root_rejected
    """
    building = create_building("Hierarchy House")
    gm = create_key_node(building["id"], "GRAND_MASTER", "GM")

    resp = api.create_key_node(
        {"building_id": building["id"], "parent_id": gm["id"], "level": "CHANGE",
         "label": "SKIP"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_KEY_HIERARCHY_INVALID)

    resp = api.create_key_node(
        {"building_id": building["id"], "level": "CHANGE", "label": "ROOT-CHANGE"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_KEY_HIERARCHY_INVALID)


def test_door_pinned_to_non_change_node_rejected(api):
    """PRD §3.2: "A `Door` is created by a `SecurityAdmin` with a `building_id`,
    a `door_code` unique within that building (duplicates rejected
    `ERR_DOOR_CODE_EXISTS`), and a `key_node_id` that must point at a
    `CHANGE`-level node — pinning a door to any higher level is
    `ERR_KEY_HIERARCHY_INVALID`."

    Design: Corner/entities/door_pinned_to_non_change_node_rejected
    """
    building = create_building("Pin House")
    master = create_key_node(building["id"], "MASTER", "M")
    resp = api.create_door(
        {"building_id": building["id"], "door_code": "D-1", "key_node_id": master["id"]},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_KEY_HIERARCHY_INVALID)


def test_door_create_inherits_building_propped_threshold(api):
    """PRD §3.2: "An optional `propped_threshold_seconds` (which must be at
    least 1) overrides how long the door may stand open before run-ops raises an
    alert; when omitted, the door inherits the building's
    `default_propped_threshold_seconds`."
    PRD §3.2: "A new door starts with `hardware_status` `OPERATIONAL`,
    `core_status` `ACTIVE`, and `open_since` null."

    Design: Corner/entities/door_create_inherits_building_propped_threshold
    """
    ctx = setup_building_with_chain("Inherit House", default_propped_threshold_seconds=150)
    building, change = ctx["building"], ctx["change"]

    door_a = create_door(building["id"], change["id"], "D-A")
    assert door_a["propped_threshold_seconds"] == 150
    assert door_a["hardware_status"] == "OPERATIONAL"
    assert door_a["core_status"] == "ACTIVE"
    assert door_a["open_since"] is None

    door_b = create_door(building["id"], change["id"], "D-B", propped_threshold_seconds=45)
    assert door_b["propped_threshold_seconds"] == 45


def test_door_code_duplicate_in_same_building_rejected(api):
    """PRD §3.2: "A `Door` is created by a `SecurityAdmin` with a `building_id`,
    a `door_code` unique within that building (duplicates rejected
    `ERR_DOOR_CODE_EXISTS`), and a `key_node_id` that must point at a
    `CHANGE`-level node — pinning a door to any higher level is
    `ERR_KEY_HIERARCHY_INVALID`."

    Design: Corner/entities/door_code_duplicate_in_same_building_rejected
    """
    ctx = setup_building_with_chain("DoorCode House")
    building, change = ctx["building"], ctx["change"]
    create_door(building["id"], change["id"], "D-1")
    resp = api.create_door(
        {"building_id": building["id"], "door_code": "D-1", "key_node_id": change["id"]},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DOOR_CODE_EXISTS)


def test_credential_duplicate_serial_rejected(api):
    """PRD §3.2: "Credentials enter the world through `FrontDesk` or
    `SecurityAdmin` as stock: a `serial_no` unique within the building (else
    `ERR_SERIAL_EXISTS`), a `type` of `METAL_KEY`, `FOB`, or `CARD`, and a
    `key_node_id` naming the hierarchy node whose locks the credential operates."

    Design: Corner/entities/credential_duplicate_serial_rejected
    """
    ctx = setup_building_with_chain("Serial House")
    building, change = ctx["building"], ctx["change"]
    create_credential(building["id"], change["id"], "K-1", "METAL_KEY")
    resp = api.create_credential(
        {"building_id": building["id"], "key_node_id": change["id"],
         "serial_no": "K-1", "type": "FOB"},
        DESK,
    )
    validate_error(resp, ApiErrorId.ERR_SERIAL_EXISTS)

    data, meta = validate_paginated(
        api.list_credentials(DESK, params={"building_id": building["id"]})
    )
    assert meta["total_count"] == 1
    assert len(data) == 1


def test_resident_missing_unit_label_returns_invalid_request(api):
    """PRD §3.2: "`unit_label` is required exactly when `kind` is `RESIDENT`;
    omitting it there is `ERR_INVALID_REQUEST`."

    Design: Corner/entities/resident_missing_unit_label_returns_invalid_request
    """
    building = create_building("Required House")
    resp = api.create_person(
        {"building_id": building["id"], "full_name": "No Unit", "kind": "RESIDENT"},
        DESK,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_credential_create_status_input_ignored(api):
    """PRD §3.2: "A new credential has `status` `IN_STOCK`, null
    `holder_person_id`, null `issued_at`, null `expires_at`, null `lost_at`, and
    null `deactivated_reason`."

    Design: Corner/entities/credential_create_status_input_ignored
    """
    ctx = setup_building_with_chain("System Field House")
    building, change = ctx["building"], ctx["change"]
    resp = api.create_credential(
        {"building_id": building["id"], "key_node_id": change["id"],
         "serial_no": "X-1", "type": "FOB", "status": "ISSUED"},
        DESK,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "IN_STOCK"
    assert data["holder_person_id"] is None


def test_access_event_has_no_version_or_update_surface(api):
    """PRD §2.5: "The exception is `AccessEvent`: audit rows carry only `id` and
    `created_at`; both `updated_at` and `version` are absent because events are
    immutable once appended."
    PRD §3.3: "Under mode `RECORDED`, an `AccessEvent` row is appended capturing
    `building_id` (copied from the door), `credential_id`, `door_id`, the
    logical-clock `occurred_at`, and the winning `outcome`; additionally, when
    the outcome is `GRANTED` and the door's `open_since` is currently null,
    `open_since` is set to now — but re-scans while the door already shows open
    do not refresh it."

    Design: Corner/entities/access_event_has_no_version_or_update_surface
    """
    ctx = setup_building_with_chain("Audit House", with_door=True)
    building, change, door = ctx["building"], ctx["change"], ctx["door"]
    set_clock("2026-08-01T08:00:00Z")
    staff = create_person(building["id"], "Staff One", "STAFF")
    cred = create_credential(building["id"], change["id"], "K-1", "FOB")
    issue_credential(cred["id"], staff["id"])
    create_access_group(building["id"], "All", door_ids=[door["id"]],
                        person_ids=[staff["id"]])

    result = access_check(door["id"], cred["id"], mode="RECORDED")
    assert result["outcome"] == "GRANTED"
    assert result["access_event_id"] is not None

    event = validate_success(api.get_access_event(result["access_event_id"], OFFICER))
    assert_access_event(event)
    assert event["outcome"] == "GRANTED"
    assert_timestamp_equals(event["occurred_at"], "2026-08-01T08:00:00Z")
    assert event["archived"] is False
