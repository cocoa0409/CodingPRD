"""Maintenance windows, optimistic concurrency, versioning, and general CRUD /
validation / pagination / RBAC surface."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    create_machine_payload, create_flavor_payload, post_adjustment_payload,
    make_machine, make_flavor, make_loyalty, make_reconciliation,
    make_maintenance_window, current_machine_version,
)

MANAGER = TEST_USERS["manager_headers"]
SHIFTLEAD = TEST_USERS["shiftlead_headers"]
CASHIER = TEST_USERS["cashier_headers"]


def test_overlapping_maintenance_window_conflict_rejected(api):
    """PRD §3.10: "a spacing guard, which requires the new window to sit at least
    `MAINTENANCE_BUFFER_MINUTES` away from every already-`SCHEDULED` window on the
    same machine — treating each window as a closed interval padded by the buffer
    on both sides — and rejects a violation with `ERR_MAINTENANCE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/maintenance_buffer_overlap_rejected
    """
    machine = make_machine(api, mix_par_oz=1000)
    make_maintenance_window(api, machine["id"], "2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z", machine["version"])
    v2 = current_machine_version(api, machine["id"])
    # window2 [10:30,11:30) directly overlaps window1 [10:00,11:00) -> conflict for any buffer >= 0.
    resp = api.create_maintenance_window(
        {"machine_id": machine["id"], "window_start": "2026-03-05T10:30:00Z",
         "window_end": "2026-03-05T11:30:00Z", "expected_machine_version": v2}, SHIFTLEAD)
    validate_error(resp, ApiErrorId.ERR_MAINTENANCE_WINDOW_CONFLICT.value)


def test_far_apart_maintenance_window_scheduled(api):
    """PRD §3.10: "A new window's `status` is `SCHEDULED`. Two guards apply at
    creation: the OCC guard, which rejects a stale `expected_machine_version`
    with `ERR_STALE_VERSION`; and a spacing guard, which requires the new window
    to sit at least `MAINTENANCE_BUFFER_MINUTES` away from every already-
    `SCHEDULED` window on the same machine"

    Design: Difficulty/resource_temporal_overlap/maintenance_buffer_overlap_rejected
    """
    machine = make_machine(api, mix_par_oz=1000)
    make_maintenance_window(api, machine["id"], "2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z", machine["version"])
    v2 = current_machine_version(api, machine["id"])
    # window2 a full month later -> no minute-scale buffer can reach it.
    resp = api.create_maintenance_window(
        {"machine_id": machine["id"], "window_start": "2026-04-05T10:00:00Z",
         "window_end": "2026-04-05T11:00:00Z", "expected_machine_version": v2}, SHIFTLEAD)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SCHEDULED"


def test_maintenance_window_end_before_start_rejected(api):
    """PRD §3.10: "a `window_end` (exclusive) that must be strictly after the
    start (otherwise `ERR_INVALID_WINDOW`)"

    Design: Corner/validations/invalid_window_end_before_start_rejected
    """
    machine = make_machine(api, mix_par_oz=1000)
    resp = api.create_maintenance_window(
        {"machine_id": machine["id"], "window_start": "2026-03-05T12:00:00Z",
         "window_end": "2026-03-05T11:00:00Z", "expected_machine_version": machine["version"]}, SHIFTLEAD)
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)


def test_stale_machine_version_maintenance_rejected(api):
    """PRD §2.9: "Because a successful schedule re-stamps `next_maintenance_at`
    and increments the machine's `version`, a second request that still carries
    the pre-supersede value is stale; if `expected_machine_version` does not equal
    the machine's current `version`, the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_maintenance_window_stale_version
    """
    machine = make_machine(api, mix_par_oz=1000)
    stale_version = machine["version"]
    make_maintenance_window(api, machine["id"], "2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z", stale_version)
    # window2 far apart in time (no spacing conflict), but carries the stale version.
    resp = api.create_maintenance_window(
        {"machine_id": machine["id"], "window_start": "2026-03-20T10:00:00Z",
         "window_end": "2026-03-20T11:00:00Z", "expected_machine_version": stale_version}, SHIFTLEAD)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_stale_reconciliation_version_adjustment_rejected(api):
    """PRD §2.9: "Each posted adjustment re-derives those totals and increments
    the reconciliation's `version`, so an adjustment carrying the pre-supersede
    value is stale; if `expected_daily_reconciliation_version` does not equal the
    reconciliation's current `version`, the post is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_reconciliation_adjustment_stale_version
    """
    recon = make_reconciliation(api)
    stale_version = recon["version"]
    validate_success(api.post_adjustment(recon["id"], post_adjustment_payload(100, stale_version, reason="till float"), MANAGER), expected_status=201)
    resp = api.post_adjustment(recon["id"], post_adjustment_payload(50, stale_version, reason="second post"), MANAGER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_version_increments_by_one_on_mutation(api):
    """PRD §2.5: "`version`, an integer that starts at its initial value and
    increments by one on every mutation."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_mutation
    """
    loyalty = make_loyalty(api)
    created_version = loyalty["version"]
    suspended = validate_success(api.suspend_loyalty(loyalty["id"], MANAGER))
    assert suspended["version"] == created_version + 1, \
        f"version must increment by exactly one on mutation, {created_version} -> {suspended['version']}"
    assert suspended["status"] == "SUSPENDED"


def test_get_machine_not_found(api):
    """PRD §2.7: "The not-found codes are resource-specific:
    `ERR_MACHINE_NOT_FOUND`, `ERR_FLAVOR_NOT_FOUND`, `ERR_TOPPING_NOT_FOUND`,
    `ERR_PROMOTION_NOT_FOUND`, `ERR_LOYALTY_NOT_FOUND`, `ERR_VOUCHER_NOT_FOUND`,
    `ERR_TICKET_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, `ERR_WASTE_NOT_FOUND`,
    `ERR_WINDOW_NOT_FOUND`, `ERR_RESOURCE_NOT_FOUND` (catering resource),
    `ERR_CATERING_NOT_FOUND` (catering order), and `ERR_RECONCILIATION_NOT_FOUND`."

    Design: Corner/entities/get_machine_not_found
    """
    resp = api.get_machine(NON_EXISTENT_UUID, CASHIER)
    validate_error(resp, ApiErrorId.ERR_MACHINE_NOT_FOUND.value)


def test_create_flavor_missing_price_rejected(api):
    """PRD §2.7: "A malformed body — a missing required field or a value of the
    wrong type — is rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_flavor_missing_required_price
    """
    machine = make_machine(api, mix_par_oz=1000)
    resp = api.create_flavor(
        {"machine_id": machine["id"], "name": "Tart", "cost_per_oz_cents": 20}, SHIFTLEAD)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_flavor_bad_machine_not_found(api):
    """PRD §2.7: "then existence of every referenced resource (the `ERR_*_NOT_FOUND`
    family, HTTP 404)"
    PRD §2.7: "Existence is checked left-to-right: path identifiers are resolved
    before body foreign keys, and the first identifier that fails to resolve
    determines the 404."

    Design: Corner/entities/create_flavor_bad_machine_returns_not_found
    """
    resp = api.create_flavor(
        create_flavor_payload(NON_EXISTENT_UUID, name="Tart"), SHIFTLEAD)
    validate_error(resp, ApiErrorId.ERR_MACHINE_NOT_FOUND.value)


def test_flavors_filterable_by_machine_id(api):
    """PRD §3.2: "Flavors can be listed and filtered by `machine_id` and
    `status`."

    Design: Corner/entities/flavor_machine_id_reverse_reachable
    """
    machine = make_machine(api, mix_par_oz=1000)
    flavor = make_flavor(api, machine["id"])
    data, meta = validate_paginated(api.list_flavors(CASHIER, params={"machine_id": machine["id"]}))
    assert len(data) == 1, f"filtering by machine_id must return exactly the one loaded flavor, got {len(data)}"
    assert data[0]["id"] == flavor["id"]


def test_list_machines_pagination_reports_has_more(api):
    """PRD §2.3: "Every list-based response echoes `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/list_machines_pagination_has_more
    """
    make_machine(api, name="Barrel-A", mix_par_oz=1000)
    make_machine(api, name="Barrel-B", mix_par_oz=1000)
    data, meta = validate_paginated(api.list_machines(CASHIER, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, f"total_count must be 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"has_more must be true with limit 1 of 2, got {meta['has_more']}"


def test_cashier_cannot_create_machine(api):
    """PRD §2.1: "When an operator attempts an action their role does not
    authorize, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/cashier_cannot_create_machine
    """
    resp = api.create_machine(create_machine_payload(name="Barrel-A", mix_par_oz=1000), CASHIER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
