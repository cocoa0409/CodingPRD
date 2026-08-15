"""Programs, retention policies, and storage locations (PRD §3.1, §2.6, §2.8)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_instant_equals,
    create_item,
    create_item_payload,
    create_location,
    create_policy,
    create_program,
    create_retention_policy_payload,
    get_location,
    get_program,
    make_intake_officer_headers,
    setup_program_policy_location,
    setup_stored_item,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]


def test_retention_policy_supersede_deactivates_old_and_guides_intake(api):
    """PRD §3.1: "Creating a policy supersedes any currently active policy with
    the same key triple: the superseded policy's `active` flips to false and its
    version increments, and the parent program's version increments as well."
    PRD §3.2: "The server looks up the active retention policy matching the
    item's `program_id`, `category`, and computed `value_tier`" and for TRANSIT
    "the deadline is `found_at` plus `retention_days` times 24 hours".

    Design: Corner/endpoints/retention_policy_supersede_action
    """
    program = create_program("TRANSIT")
    old_policy = create_policy(program["id"], retention_days=10)
    new_policy = create_policy(program["id"], retention_days=20)
    location = create_location(program["id"])

    old_after = validate_success(
        api.get_retention_policy(old_policy["id"], ADMIN), 200)
    new_after = validate_success(
        api.get_retention_policy(new_policy["id"], ADMIN), 200)
    assert old_after["active"] is False, "superseded policy must flip active to false"
    assert new_after["active"] is True, "new policy must be active"

    item = create_item(program["id"], location["id"],
                       declared_value_cents=5000, found_at="2026-08-01T09:00:00Z")
    assert item["retention_policy_id"] == new_policy["id"], (
        "intake must resolve the active (new) policy for the key triple")
    # TRANSIT hour-precise: 2026-08-01T09:00:00Z + 20 * 24h.
    assert_instant_equals(item["retention_deadline"], "2026-08-21T09:00:00Z")


def test_storage_location_under_missing_program_not_found(api, program_admin_headers):
    """PRD §2.8: "any identifier referenced in a request body must resolve to an
    existing resource. This applies wherever a payload names a `program_id`
    (item intake, policy creation, storage-location creation, venue creation,
    event creation, inquiry submission)" and "An unresolvable body reference is
    rejected with `ERR_NOT_FOUND`".

    Design: Corner/entities/storage_location_child_of_missing_program_not_found
    """
    res = api.create_storage_location(
        {"program_id": NON_EXISTENT_UUID, "name": "Cage X",
         "capacity_slots": 5, "supports_high_value": False},
        program_admin_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_deactivate_occupied_location_rejected(api, program_admin_headers):
    """PRD §3.1: "A location can be deactivated only while its `occupied_slots`
    count (§2.9) is zero — deactivating a non-empty location is rejected with
    `ERR_LOCATION_NOT_EMPTY`".

    Design: Corner/errors/err_location_not_empty_rejected
    """
    ctx = setup_stored_item(declared_value_cents=5000)

    res = api.deactivate_storage_location(ctx.location["id"], program_admin_headers)
    validate_error(res, ApiErrorId.ERR_LOCATION_NOT_EMPTY, expected_status=409)

    after = get_location(ctx.location["id"])
    assert after["active"] is True, "occupied location must remain active"
    assert after["occupied_slots"] == 1, "the STORED item still occupies its slot"


def test_intake_under_deactivated_program_rejected(api, program_admin_headers):
    """PRD §3.1: "an inactive program rejects new item intake and rejects
    publishing of its stored items with `ERR_PROGRAM_INACTIVE` (HTTP 409)".

    Design: Corner/errors/err_program_inactive_rejected
    """
    ctx = setup_program_policy_location()
    validate_success(api.deactivate_program(ctx.program["id"], program_admin_headers), 200)

    res = api.create_item(
        create_item_payload(ctx.program["id"], ctx.location["id"]),
        make_intake_officer_headers("officer-intake-1"))
    validate_error(res, ApiErrorId.ERR_PROGRAM_INACTIVE, expected_status=409)


def test_policy_create_with_stale_program_version_rejected(api, program_admin_headers):
    """PRD §2.6: "Creating a retention policy requires `expected_program_version`
    matching the owning program's current `version`. A mismatch is rejected with
    `ERR_STALE_PROGRAM_VERSION` (HTTP 412), because the policy set the
    administrator reviewed is no longer current."
    PRD §3.1: "the parent program's version increments as well."

    Design: Corner/cross_cutting_layers/occ_policy_stale_program_version_returns_412
    """
    program = create_program("TRANSIT")
    stale_version = program["version"]

    # First policy creation succeeds and bumps the program version.
    create_policy(program["id"], value_tier="LOW", expected_version=stale_version)
    program_after = get_program(program["id"])
    assert program_after["version"] == stale_version + 1, (
        "policy creation increments the parent program's version")

    # Second creation carrying the pre-supersede program version is rejected.
    res = api.create_retention_policy(
        create_retention_policy_payload(
            program["id"], stale_version, value_tier="MID", retention_days=30),
        program_admin_headers)
    validate_error(res, ApiErrorId.ERR_STALE_PROGRAM_VERSION, expected_status=412)
