"""Optimistic concurrency control on the two guarded patch endpoints and
immediate read-after-write visibility."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_access_group,
    get_door,
    setup_building_with_chain,
    validate_error,
    validate_success,
    create_building,
    create_door,
)

ADMIN = TEST_USERS["security_admin_headers"]
OFFICER = TEST_USERS["security_officer_headers"]


def test_occ_access_group_stale_patch_rejected(api):
    """PRD §2.7: "A request to patch an access group must carry
    `expected_access_group_version` holding the group's `version` as the client
    last observed it; if another writer has advanced the group's `version` since
    that observation — for example by editing `door_ids`, `person_ids`, or the
    schedule — the request is rejected with `ERR_STALE_VERSION` (HTTP 412),
    because the client's view of the group is stale."
    PRD §2.5: "Every primary resource carries `id` (a server-minted UUID with no
    type prefix), `created_at` (ISO 8601 UTC, three fractional digits),
    `updated_at` (same format, refreshed on any mutation), and `version` (an
    integer starting at 1, incremented on every mutation)."

    Design: Corner/cross_cutting_layers/occ_access_group_stale_patch_rejected
    """
    building = create_building("OCC House")
    group = create_access_group(building["id"], "G", days_of_week=["MON"],
                                window_start_utc="08:00", window_end_utc="17:00")
    assert group["version"] == 1

    patched = validate_success(api.patch_access_group(
        group["id"], {"expected_access_group_version": 1, "name": "G-Renamed"}, ADMIN
    ))
    assert patched["version"] == 2

    resp = api.patch_access_group(
        group["id"], {"expected_access_group_version": 1, "name": "G-Stale"}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    current = validate_success(api.get_access_group(group["id"], ADMIN))
    assert current["name"] == "G-Renamed"


def test_occ_door_stale_patch_rejected(api):
    """PRD §2.7: "The same rule governs patching a door: the request must carry
    `expected_door_version` matching the door's current `version`, and a
    mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_door_stale_patch_rejected
    """
    ctx = setup_building_with_chain("OCC Door House", with_door=True)
    door = ctx["door"]
    assert door["version"] == 1

    patched = validate_success(api.patch_door(
        door["id"], {"expected_door_version": 1, "propped_threshold_seconds": 300}, ADMIN
    ))
    assert patched["version"] == 2

    resp = api.patch_door(
        door["id"], {"expected_door_version": 1, "propped_threshold_seconds": 999}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert get_door(door["id"])["propped_threshold_seconds"] == 300


def test_immediate_visibility_of_writes(api):
    """PRD §3.2: "Doors can be listed with `building_id`, `key_node_id`,
    `hardware_status`, and `core_status` filters, and patched later to change
    `propped_threshold_seconds` under the OCC rule of §2.7, which bumps
    `version` by 1."
    PRD §2.5: "Every primary resource carries `id` (a server-minted UUID with no
    type prefix), `created_at` (ISO 8601 UTC, three fractional digits),
    `updated_at` (same format, refreshed on any mutation), and `version` (an
    integer starting at 1, incremented on every mutation)."

    Design: Corner/consistency_model/immediate_visibility_of_writes
    """
    ctx = setup_building_with_chain("Immediate House", with_door=True)
    door = ctx["door"]
    validate_success(api.patch_door(
        door["id"], {"expected_door_version": door["version"],
                     "propped_threshold_seconds": 240},
        ADMIN,
    ))
    after = validate_success(api.get_door(door["id"], OFFICER))
    assert after["propped_threshold_seconds"] == 240
    assert after["version"] == 2
