"""Ingest batches, asset intake, staff registry, pagination, and the logical clock."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    is_valid_uuid, ApiErrorId, NON_EXISTENT_UUID,
    create_asset_payload, create_ingest_batch_payload, create_staff_member_payload,
    create_open_batch, create_asset, create_staff_member, create_cataloged_asset,
    create_ready_proxy, create_rights_grant, get_asset,
    TEST_USERS,
)

ARCHIVIST = TEST_USERS["archivist_lead_headers"]
INGEST = TEST_USERS["ingest_coordinator_headers"]
ADMIN = TEST_USERS["system_admin_headers"]


def test_ingest_batch_create_returns_open_with_zero_assets(api):
    """PRD §3.1: "A new batch is `OPEN` and its `asset_count` is zero".
    PRD §2.5: "The `id` is a server-minted UUID with no type prefix."

    Design: Corner/entities/ingest_batch_create_defaults
    """
    res = api.create_ingest_batch(
        create_ingest_batch_payload(batch_name="B1", source_department="NEWS"), INGEST)
    batch = validate_success(res, 201)
    assert batch["status"] == "OPEN"
    assert batch["asset_count"] == 0
    assert is_valid_uuid(batch["id"])

    fetched = validate_success(api.get_ingest_batch(batch["id"], INGEST), 200)
    assert fetched["status"] == "OPEN"
    assert fetched["asset_count"] == 0


def test_asset_create_missing_title_rejected(api):
    """PRD §3.1: "a non-positive value, a missing required field, a wrong type, or an
    unknown enum value anywhere in the payload is a malformed request rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/asset_create_missing_title_returns_invalid_request
    """
    batch = create_open_batch()
    payload = create_asset_payload(batch["id"])
    del payload["title"]
    res = api.create_asset(payload, INGEST)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_fresh_asset_computed_fields(api):
    """PRD §3.1: "A freshly ingested asset has `catalog_status` `METADATA_DRAFT`,
    `storage_tier` `ONLINE`, and no `metadata_submitted_by_user_id`."
    PRD §3.1: "`source_asset_id` is system-set and stays null for originals".
    PRD §3.3: "If the effective set is empty, the posture is `EXPIRED`."
    PRD §3.1: "it grows by one each time an asset is ingested under the batch."

    Design: Corner/entities/asset_create_computed_posture_input_ignored
    """
    batch = create_open_batch()
    asset = validate_success(api.create_asset(
        create_asset_payload(batch["id"]), INGEST), 201)
    assert asset["catalog_status"] == "METADATA_DRAFT"
    assert asset["storage_tier"] == "ONLINE"
    assert asset["rights_posture"] == "EXPIRED"
    assert asset["source_asset_id"] is None
    assert asset["metadata_submitted_by_user_id"] is None

    fetched = validate_success(api.get_asset(asset["id"], ARCHIVIST), 200)
    assert fetched["rights_posture"] == "EXPIRED"
    assert fetched["hold_status"] == "CLEAR"

    batch_after = validate_success(api.get_ingest_batch(batch["id"], INGEST), 200)
    assert batch_after["asset_count"] == 1


def test_asset_create_unknown_format_enum_rejected(api):
    """PRD §3.1: "a non-positive value, a missing required field, a wrong type, or an
    unknown enum value anywhere in the payload is a malformed request rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/asset_create_invalid_format_enum_returns_invalid_request
    """
    batch = create_open_batch()
    payload = create_asset_payload(batch["id"], format_class="LASERDISC")
    res = api.create_asset(payload, INGEST)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_asset_get_not_found(api):
    """PRD §2.6: "Path identifiers are validated left to right, then body foreign-key
    references; the first unknown id yields that resource's not-found error (HTTP 404):
    `ERR_STAFF_MEMBER_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`".

    Design: Corner/entities/asset_get_not_found_returns_404
    """
    res = api.get_asset(NON_EXISTENT_UUID, ARCHIVIST)
    validate_error(res, ApiErrorId.ERR_ASSET_NOT_FOUND)


def test_asset_list_pagination_has_more(api):
    """PRD §2.3: "List endpoints accept two query parameters: `limit` (default 10,
    minimum 1, maximum 100) and `offset` (default 0)."
    PRD §2.3: "The `meta` object of a list response carries four pagination fields:
    `limit`, `offset`, `total_count`, and `has_more`, where `has_more` reports whether
    additional rows exist beyond the returned window."

    Design: Corner/entities/asset_list_pagination_has_more
    """
    batch = create_open_batch()
    for title in ("A", "B", "C"):
        create_asset(batch["id"], title=title)

    data, meta = validate_paginated(api.list_assets(
        ARCHIVIST, params={"ingest_batch_id": batch["id"], "limit": 2, "offset": 0}))
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    data2, meta2 = validate_paginated(api.list_assets(
        ARCHIVIST, params={"ingest_batch_id": batch["id"], "limit": 2, "offset": 2}))
    assert len(data2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_staff_member_duplicate_email_rejected(api):
    """PRD §3.1: "Staff email addresses are unique across the registry — a duplicate
    `email` is rejected with `ERR_DUPLICATE_STAFF_EMAIL` (HTTP 422)."

    Design: Corner/entities/staff_member_duplicate_email_rejected
    """
    create_staff_member(email="r@x.com", full_name="R")
    res = api.create_staff_member(
        create_staff_member_payload(email="r@x.com", full_name="R2"), ADMIN)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_STAFF_EMAIL)


def test_batch_finalize_gates_and_lockdown(api):
    """PRD §3.1: "Finalizing a batch moves it from `OPEN` to `FINALIZED` and is
    permitted only when the batch contains at least one asset (otherwise
    `ERR_EMPTY_BATCH`, HTTP 409) and no asset in the batch still sits in
    `METADATA_DRAFT` (otherwise `ERR_BATCH_ASSETS_UNRESOLVED`, HTTP 409)."
    PRD §3.1: "`FINALIZED` is terminal: once a batch is finalized, any further asset
    ingest targeting it is rejected with `ERR_BATCH_NOT_OPEN` (HTTP 409)."

    Design: Corner/endpoints/batch_finalize_empty_and_unresolved_gates
    """
    b1 = create_open_batch()
    res1 = api.finalize_ingest_batch(b1["id"], INGEST)
    validate_error(res1, ApiErrorId.ERR_EMPTY_BATCH)

    b2 = create_open_batch()
    create_asset(b2["id"])  # stays METADATA_DRAFT
    res2 = api.finalize_ingest_batch(b2["id"], INGEST)
    validate_error(res2, ApiErrorId.ERR_BATCH_ASSETS_UNRESOLVED)

    # Boundary: exactly one resolved (IN_REVIEW) asset finalizes OK.
    b3 = create_open_batch()
    a3 = create_asset(b3["id"])
    validate_success(api.submit_metadata(a3["id"], TEST_USERS["metadata_cataloger_headers"]), 200)
    finalized = validate_success(api.finalize_ingest_batch(b3["id"], INGEST), 200)
    assert finalized["status"] == "FINALIZED"

    res3 = api.create_asset(create_asset_payload(b3["id"], title="LATE"), INGEST)
    validate_error(res3, ApiErrorId.ERR_BATCH_NOT_OPEN)


def test_immediate_consistency_of_mutations(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."
    PRD §3.1: "it grows by one each time an asset is ingested under the batch."

    Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_response
    """
    asset = create_cataloged_asset()
    create_ready_proxy(asset["id"])
    create_rights_grant(asset["id"])
    archived = validate_success(api.archive_asset(asset["id"], ARCHIVIST), 200)
    assert archived["catalog_status"] == "ARCHIVED", (
        "archive response body must carry the post-transition catalog_status")

    batch = validate_success(api.get_ingest_batch(asset["ingest_batch_id"], ARCHIVIST), 200)
    assert batch["asset_count"] == 1, (
        "immediately following GET must already reflect the create-time increment")


def test_default_clock_is_fixed_epoch(api):
    """PRD §2.4: "At startup, before any operator action, the logical clock reads
    exactly 2026-08-01T00:00:00Z."
    PRD §3.3: "The effective grant set consists of the asset's `ACTIVE` grants whose
    window contains the current logical instant — `window_start` at or before now,
    `window_end` strictly after now".

    Design: Corner/cross_cutting_layers/clock_default_is_fixed_epoch
    """
    asset = create_asset()
    assert asset["created_at"].startswith("2026-08-01T00:00:00"), (
        f"asset created before any clock call must carry the fixed epoch, got {asset['created_at']}")
    create_rights_grant(asset["id"])  # window [2026-01-01, 2027-01-01)
    fetched = validate_success(api.get_asset(asset["id"], ARCHIVIST), 200)
    assert fetched["rights_posture"] == "CLEARED", (
        "window_start 2026-01-01 must already be effective at the default clock")
