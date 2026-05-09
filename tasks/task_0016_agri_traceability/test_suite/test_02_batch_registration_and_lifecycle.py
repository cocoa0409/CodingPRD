"""Planting batch registration validations + lifecycle transitions (PRD §3.2)."""
import pytest

from test_helpers import (
    api_client as api,
    validate_success,
    validate_error,
    assert_planting_batch,
    create_planting_batch_payload,
    unique_batch_code,
    make_grower_headers,
    DEFAULT_GROWER_ID,
    DEFAULT_GROWER_ID_ALT,
    create_planting_batch,
    declare_growing,
    setup_batch_growing,
    TEST_USERS,
)


# --------------------------------------------------------------------------
# PRD §3.2 — batch_code format / uniqueness
# --------------------------------------------------------------------------

@pytest.mark.parametrize("bad_code", [
    "PB-lowercase",
    "PB-1234567",       # 7 chars (too short)
    "PB-123456789",     # 9 chars (too long)
    "PB-ABCDE@12",      # special char
    "Foo-12345678",     # wrong prefix
    "12345678",         # missing prefix
])
def test_invalid_batch_code_format_rejected(bad_code):
    """PRD §3.2: "The grower supplies a human-readable batch_code matching the
    pattern ^PB-[A-Z0-9]{8}$ (uppercase alphanumeric, 8 characters after the
    prefix); duplicate or malformed codes are rejected with
    ERR_BATCH_CODE_INVALID."

    Claim: malformed batch_code → ERR_BATCH_CODE_INVALID.
    """
    headers = make_grower_headers(DEFAULT_GROWER_ID)
    payload = create_planting_batch_payload(batch_code=bad_code)
    res = api.create_planting_batch(payload, headers)
    validate_error(res, "ERR_BATCH_CODE_INVALID")


def test_duplicate_batch_code_rejected():
    """PRD §3.2: "duplicate or malformed codes are rejected with
    ERR_BATCH_CODE_INVALID."

    Claim: a second batch with the same batch_code → ERR_BATCH_CODE_INVALID.
    """
    headers = make_grower_headers(DEFAULT_GROWER_ID)
    code = unique_batch_code()
    res1 = api.create_planting_batch(create_planting_batch_payload(batch_code=code), headers)
    validate_success(res1, 201)
    res2 = api.create_planting_batch(create_planting_batch_payload(batch_code=code), headers)
    validate_error(res2, "ERR_BATCH_CODE_INVALID")


# --------------------------------------------------------------------------
# PRD §3.2 — date sanity
# --------------------------------------------------------------------------

def test_planting_after_expected_harvest_start_rejected():
    """PRD §3.2: "the planting date must be on or before the expected harvest
    start, and the expected harvest end must be on or after the expected
    harvest start; any violation yields ERR_PLANTING_DATES_INVALID."

    Claim: planting_date > expected_harvest_start → ERR_PLANTING_DATES_INVALID.
    """
    headers = make_grower_headers(DEFAULT_GROWER_ID)
    payload = create_planting_batch_payload(
        planting_date="2026-05-10T00:00:00.000Z",
        expected_harvest_start="2026-05-01T00:00:00.000Z",
        expected_harvest_end="2026-06-01T00:00:00.000Z",
    )
    res = api.create_planting_batch(payload, headers)
    validate_error(res, "ERR_PLANTING_DATES_INVALID")


def test_expected_harvest_end_before_start_rejected():
    """PRD §3.2: "the expected harvest end must be on or after the expected
    harvest start ... any violation yields ERR_PLANTING_DATES_INVALID."

    Claim: expected_harvest_end < expected_harvest_start →
    ERR_PLANTING_DATES_INVALID.
    """
    headers = make_grower_headers(DEFAULT_GROWER_ID)
    payload = create_planting_batch_payload(
        planting_date="2026-01-01T00:00:00.000Z",
        expected_harvest_start="2026-05-01T00:00:00.000Z",
        expected_harvest_end="2026-04-01T00:00:00.000Z",
    )
    res = api.create_planting_batch(payload, headers)
    validate_error(res, "ERR_PLANTING_DATES_INVALID")


# --------------------------------------------------------------------------
# PRD §3.2 — initial state and identity capture
# --------------------------------------------------------------------------

def test_new_batch_starts_in_registered_with_clean_posture():
    """PRD §3.2: "A newly registered batch starts in REGISTERED with posture
    CLEAN, recall_status NONE, total_quantity_kg 0, and earliest_legal_harvest_date
    null."

    Claim: a freshly created batch carries the documented defaults.
    """
    headers = make_grower_headers(DEFAULT_GROWER_ID)
    res = api.create_planting_batch(create_planting_batch_payload(), headers)
    batch = validate_success(res, 201)
    assert_planting_batch(batch)
    assert batch["status"] == "REGISTERED"
    assert batch["posture"] == "CLEAN"
    assert batch["recall_status"] == "NONE"
    assert batch["total_quantity_kg"] == 0
    assert batch.get("earliest_legal_harvest_date") in (None, "", 0)


def test_grower_id_captured_from_x_user_id():
    """PRD §3.2: "The registering grower's X-User-ID is captured as grower_id
    on the batch."

    Claim: batch.grower_id equals the X-User-ID of the registering grower.
    """
    headers = make_grower_headers(DEFAULT_GROWER_ID_ALT)
    res = api.create_planting_batch(create_planting_batch_payload(), headers)
    batch = validate_success(res, 201)
    assert batch["grower_id"] == DEFAULT_GROWER_ID_ALT


# --------------------------------------------------------------------------
# PRD §3.2 — state transitions
# --------------------------------------------------------------------------

def test_declare_growing_transitions_registered_to_growing():
    """PRD §3.2: "A grower may explicitly advance a batch from REGISTERED to
    GROWING without first recording an application; this declaration carries
    no body."

    Claim: declare-growing on a REGISTERED batch yields status GROWING.
    """
    batch = create_planting_batch()
    res = api.declare_growing(batch["id"], make_grower_headers(batch["grower_id"]))
    advanced = validate_success(res, 200)
    assert advanced["status"] == "GROWING"


def test_declare_growing_again_rejected_with_invalid_state():
    """PRD §2.11: "State-machine validity comes after that, returning
    ERR_INVALID_STATE when the target resource is in a state that does not
    admit the requested transition."

    Claim: declare-growing on an already-GROWING batch → ERR_INVALID_STATE.
    """
    batch = setup_batch_growing()
    res = api.declare_growing(batch["id"], make_grower_headers(batch["grower_id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_grower_cannot_act_on_other_growers_batch():
    """PRD §2.1: "A grower may only operate on planting batches whose grower_id
    matches their own X-User-ID."

    Claim: Grower A trying to declare-growing Grower B's batch → ERR_FORBIDDEN.
    """
    batch = create_planting_batch(grower_id=DEFAULT_GROWER_ID)
    foreign = make_grower_headers(DEFAULT_GROWER_ID_ALT)
    res = api.declare_growing(batch["id"], foreign)
    validate_error(res, "ERR_FORBIDDEN")


# --------------------------------------------------------------------------
# PRD §2.4 — common-field response contract
# --------------------------------------------------------------------------

def test_planting_batch_carries_common_fields():
    """PRD §2.4: "Most primary entities — PlantingBatch, ... — carry the
    standard system-managed fields: id ... created_at ... updated_at ...
    version."

    Claim: a PlantingBatch response has id, created_at, updated_at, version.
    """
    batch = create_planting_batch()
    assert "id" in batch and isinstance(batch["id"], str)
    assert "created_at" in batch
    assert "updated_at" in batch
    assert "version" in batch and isinstance(batch["version"], int)


# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------

def test_planting_batch_list_pagination(regulatory_headers):
    """PRD §2.3: "Paginated and list-based responses include the following
    fields in the meta object of the response envelope: limit, offset,
    total_count, and has_more."

    Claim: the list endpoint reports limit/offset/total_count/has_more.
    """
    from test_helpers import validate_paginated
    # Seed at least 3 batches
    for _ in range(3):
        create_planting_batch()
    res = api.list_planting_batches(regulatory_headers, params={"limit": 2, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert "total_count" in meta
    assert "has_more" in meta
    assert len(data) <= 2
