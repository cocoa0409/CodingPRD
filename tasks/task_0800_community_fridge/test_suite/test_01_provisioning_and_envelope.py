"""Provisioning, response envelope, and optimistic-concurrency version behavior."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_fridge, assert_batch,
    setup_fridge_and_steward, new_fridge, new_steward, get_fridge_version,
    reset_clock, intake_batch,
    make_admin_headers, make_steward_headers,
    create_batch_payload, FAKE_UUID,
)


def test_create_fridge_starts_operational_with_full_free_slots(api):
    """PRD §3.1: "On creation the fridge starts fully available: its `safety_posture`
    is `OPERATIONAL`, its `stock_slots_used` is zero and `free_slots` equals
    `capacity_slots`, all budget figures are zero, its `active_recall_count` and
    `ops_run_index` are zero, its `current_temp_c` starts at 4.0 degrees, and its
    `last_cleaned_at` defaults to the moment of creation."

    Design: Corner/entities/fridge_creation_sets_computed_ledgers_and_posture
    """
    reset_clock(api)
    resp = api.create_fridge(
        {"name": "New Fridge", "location_label": "Main St", "capacity_slots": 8},
        make_admin_headers(),
    )
    data = validate_success(resp, 201)
    assert_fridge(data)
    assert data["safety_posture"] == "OPERATIONAL"
    assert data["free_slots"] == 8
    assert data["stock_slots_used"] == 0
    assert data["budget_available_cents"] == 0
    assert data["budget_granted_cents"] == 0
    assert data["budget_committed_cents"] == 0


def test_create_fridge_zero_impact_and_default_temp(api):
    """PRD §3.1: "its `current_temp_c` starts at 4.0 degrees ... The
    `total_meals_provided` impact figure begins at zero."

    Design: Corner/entities/fridge_creation_sets_computed_ledgers_and_posture
    """
    reset_clock(api)
    fridge = new_fridge(api, capacity_slots=8)
    assert fridge["current_temp_c"] == 4.0
    assert fridge["total_meals_provided"] == 0
    assert fridge["active_recall_count"] == 0
    assert fridge["ops_run_index"] == 0


def test_get_nonexistent_fridge_returns_not_found(api):
    """PRD §2.5: "The system validates the identifiers in such a path from left to
    right and rejects the request with `ERR_NOT_FOUND` at the first identifier that
    does not correspond to an existing resource."

    Design: Corner/entities/get_fridge_nonexistent_returns_not_found
    """
    reset_clock(api)
    resp = api.get_fridge(FAKE_UUID, make_admin_headers())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_intake_missing_steward_id_returns_validation(api):
    """PRD §2.5: "Malformed bodies, missing required fields, invalid enum values, and
    a clock that would move backward are all reported as `ERR_VALIDATION`."

    Design: Corner/entities/intake_missing_required_steward_id_returns_validation
    """
    fridge, _ = setup_fridge_and_steward(api, capacity_slots=5)
    payload = {
        "food_category": "PRODUCE",
        "storage_type": "AMBIENT",
        "declared_quantity_kg": 3.0,
        "slot_footprint": 1,
        "intake_temp_c": 4.0,
        "use_by": "2026-04-01T00:00:00Z",
        "expected_fridge_version": fridge["version"],
    }
    resp = api.create_batch(
        fridge["id"], payload,
        make_steward_headers("11111111-1111-4111-8111-111111111111"),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_intake_produce_defaults_allergens_to_empty_list(api):
    """PRD §3.5: "a `use_by` timestamp, and an `allergens` list of labels (empty by
    default)."

    Design: Corner/entities/intake_default_allergens_empty_for_produce
    """
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=5)
    batch = intake_batch(
        api, fridge["id"], steward["id"],
        food_category="PRODUCE", storage_type="AMBIENT", declared_quantity_kg=3.0,
    )
    assert batch["allergens"] == []


def test_intake_response_uses_object_envelope_with_provisional_meals(api):
    """PRD §3.5: "The batch's `provisional_meals` is computed immediately from the
    declared mass: it is `declared_quantity_kg` divided by 1.2 kilograms per meal,
    rounded half-up to a whole number of meals."

    Design: Corner/consistency_model/intake_response_uses_success_envelope_object
    """
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=10)
    payload = create_batch_payload(
        steward["id"], fridge["version"], declared_quantity_kg=6.0,
    )
    resp = api.create_batch(fridge["id"], payload, make_steward_headers(steward["id"]))
    data = validate_success(resp, 201)
    body = resp.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert data["provisional_meals"] == 5


def test_intake_with_current_version_increments_fridge_version_by_one(api):
    """PRD §3.5: "the fridge's `version` increments by one — this is the increment
    that later invalidates any stale `expected_fridge_version`."

    Design: Corner/cross_cutting_complexity_layers/intake_correct_fridge_version_increments_version
    """
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=10)
    before = fridge["version"]
    payload = create_batch_payload(steward["id"], before, declared_quantity_kg=3.0)
    validate_success(
        api.create_batch(fridge["id"], payload, make_steward_headers(steward["id"])),
        201,
    )
    after = get_fridge_version(api, fridge["id"])
    assert after == before + 1, f"expected version {before + 1}, got {after}"


def test_intake_with_stale_version_rejected_with_conflict(api):
    """PRD §2.10: "If `expected_fridge_version` does not equal the fridge's current
    `version`, the intake is rejected with `ERR_FRIDGE_VERSION_CONFLICT` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_fridge_version_on_intake_returns_412
    """
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=10)
    stale = fridge["version"]
    # First intake with the observed version succeeds and bumps the fridge version.
    intake_batch(api, fridge["id"], steward["id"], expected_version=stale,
                 declared_quantity_kg=3.0)
    # Second intake still carrying the pre-first (now stale) version is rejected.
    payload = create_batch_payload(steward["id"], stale, declared_quantity_kg=3.0)
    resp = api.create_batch(fridge["id"], payload, make_steward_headers(steward["id"]))
    validate_error(resp, ApiErrorId.ERR_FRIDGE_VERSION_CONFLICT.value)
