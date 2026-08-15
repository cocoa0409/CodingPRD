"""Harvest batches: field maturity and quality gates, pallet yield arithmetic,
availability conservation, the harvest daylight window, link/cancel rules,
and the optimistic field-version guard (PRD §2.4, §2.8, §3.3)."""
from test_helpers import (
    TEST_USERS,
    assert_field_area_conserved,
    assert_money_eq,
    create_batch,
    create_config,
    create_field,
    create_variety,
    factories,
    get_field,
    get_success_data,
    is_valid_uuid,
    mini_chain,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId

FARM = TEST_USERS["farm_manager_headers"]
SALES = TEST_USERS["sales_rep_headers"]
HARVEST = TEST_USERS["harvest_supervisor_headers"]


def _config_variety(api):
    create_config(api)
    return create_variety(api)


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency /
#   harvest_batch_gated_by_field_maturity_and_quality
# Same field config at two maturity positions: GROWING (age exactly 60)
# rejects; READY (age 61) accepts; a quality-gate flip (moisture 60) rejects.
# ---------------------------------------------------------------------------

def test_batch_create_rejected_on_growing_field_accepted_on_ready(api):
    """PRD §3.3: "The field's `maturity_state` must be `READY` or `MATURE`; anything else is rejected with `ERR_FIELD_NOT_HARVESTABLE`."
    PRD §3.2: "Comparing `age_days` with the variety's windows yields `maturity_state`: `SEEDED` while age is at most `germination_max_days`, `GROWING` while at most `growing_max_days`, `READY` while at most `ready_max_days`, `MATURE` while at most `mature_max_days`, and `OVERAGED` beyond that. Band boundaries lean young — a field whose age equals `germination_max_days` is still `SEEDED`, and likewise for the later bands."

    Design: Difficulty/cross_entity_state_dependency/harvest_batch_gated_by_field_maturity_and_quality
    """
    v = _config_variety(api)
    # Default clock 2026-08-01: planted 2026-06-02 -> age 60 -> still GROWING.
    fg = create_field(api, v["id"], name="G-60",
                      last_planted_at="2026-06-02T00:00:00Z")
    # Planted 2026-06-01 -> age 61 -> READY.
    fr = create_field(api, v["id"], name="R-61",
                      last_planted_at="2026-06-01T00:00:00Z")

    resp = api.create_harvest_batch(
        factories.create_harvest_batch_payload(
            fg["id"], fg["version"], scheduled_date="2026-08-02"
        ),
        HARVEST,
    )
    validate_error(resp, ApiErrorId.ERR_FIELD_NOT_HARVESTABLE, 409)

    batch = create_batch(api, fr["id"], scheduled_date="2026-08-02")
    assert batch["status"] == "PENDING"
    assert batch["variety_id"] == v["id"], "batch copies the field's variety"


def test_batch_create_rejected_when_quality_gate_fails(api):
    """PRD §3.3: "And the agronomic quality gate must pass as a whole — `mow_count` of at least three, the last mow less than three days before batch creation, `soil_moisture_pct` between 35 and 55 inclusive, and `health_score` of at least 70 — with any failure rejected as `ERR_FIELD_QUALITY_GATE`."
    PRD §3.2: "A `FarmManager` may later refresh the four agronomic inputs through the field's quality-update operation; that write increments the field's `version`, one of the movements the batch-scheduling guard of §2.8 watches for."

    Design: Difficulty/cross_entity_state_dependency/harvest_batch_gated_by_field_maturity_and_quality
    """
    v = _config_variety(api)
    fr = create_field(api, v["id"], name="R-61",
                      last_planted_at="2026-06-01T00:00:00Z")
    # Flip the quality gate: moisture 60 is outside [35, 55].
    updated = get_success_data(
        api.update_field_quality(fr["id"], {"soil_moisture_pct": 60}, FARM)
    )
    resp = api.create_harvest_batch(
        factories.create_harvest_batch_payload(
            fr["id"], updated["version"], scheduled_date="2026-08-02"
        ),
        HARVEST,
    )
    validate_error(resp, ApiErrorId.ERR_FIELD_QUALITY_GATE, 409)


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / field_remaining_sqft_conservation
# 25000 PENDING reservation leaves 15000; a 20000 batch is rejected while a
# 10000 batch fits; completion decrements; cancellation of PENDING does not.
# ---------------------------------------------------------------------------

def _conservation_setup(api):
    v = _config_variety(api)
    f = create_field(api, v["id"])  # 40000 sqft, READY, quality passing
    batch_a = create_batch(api, f["id"], pallet_count=250,
                           scheduled_date="2026-08-02")  # sellable 25000
    return f, batch_a


def test_availability_nets_pending_reservations(api):
    """PRD §3.3: "Scheduling reserves against the field without decrementing it. Availability nets out pending reservations: from the field's `remaining_sqft`, subtract the `sellable_sqft` of every `PENDING` batch on that same field, and a new batch whose `sellable_sqft` exceeds what remains is rejected with `ERR_BATCH_YIELD_EXCEEDS_AVAILABLE`."

    Design: Difficulty/compensating_invariant/field_remaining_sqft_conservation
    """
    f, batch_a = _conservation_setup(api)
    assert_money_eq(batch_a["sellable_sqft"], 25000, "batch A sellable_sqft")

    version = get_field(api, f["id"])["version"]
    resp = api.create_harvest_batch(
        factories.create_harvest_batch_payload(
            f["id"], version, pallet_count=200, scheduled_date="2026-08-02"
        ),
        HARVEST,
    )
    validate_error(resp, ApiErrorId.ERR_BATCH_YIELD_EXCEEDS_AVAILABLE, 422)

    # 25000 reserved leaves 15000; a 100-pallet (10000 sqft) batch fits.
    batch_c = create_batch(api, f["id"], pallet_count=100,
                           scheduled_date="2026-08-02")
    assert_money_eq(batch_c["sellable_sqft"], 10000, "batch C sellable_sqft")


def test_completion_decrements_and_cancellation_never_leaks(api):
    """PRD §3.3: "On success the batch moves from `PENDING` to `COMPLETE` and the field's `remaining_sqft` drops by the batch's `sellable_sqft` — only completion decrements; a `PENDING` batch never has. Cancelling a batch is permitted only while it is `PENDING` and still unlinked to any order; a cancelled batch leaves `remaining_sqft` untouched, keeping the availability accounting conserved."
    PRD §2.11: "Inventory is conserved per crop cycle. At any moment, a field's `remaining_sqft` plus the `sellable_sqft` of its non-cancelled completed batches in the current cycle equals its `field_sqft`."

    Design: Difficulty/compensating_invariant/field_remaining_sqft_conservation
    """
    f, batch_a = _conservation_setup(api)
    batch_c = create_batch(api, f["id"], pallet_count=100,
                           scheduled_date="2026-08-02")

    get_success_data(api.complete_harvest_batch(
        batch_a["id"],
        factories.complete_harvest_batch_payload(
            actual_harvest_start="2026-08-02T06:00:00Z",
            actual_harvest_end="2026-08-02T07:00:00Z",
        ),
        HARVEST,
    ))
    cancelled = get_success_data(api.cancel_harvest_batch(batch_c["id"], HARVEST))
    assert cancelled["status"] == "CANCELLED"

    after = get_field(api, f["id"])
    assert_money_eq(after["remaining_sqft"], 15000,
                    "40000 - 25000 (completed); the cancelled PENDING batch never decremented")
    assert_field_area_conserved(after, 25000)


# ---------------------------------------------------------------------------
# Corner: calculations / pallet_yield_shortfall_arithmetic
# ---------------------------------------------------------------------------

def test_pallet_yield_shortfall_arithmetic(api):
    """PRD §3.3: "The batch's `full_sqft` is its `pallet_count` multiplied by the grade's full-pallet coverage — `pallet_sqft_premium`, `pallet_sqft_standard`, or `pallet_sqft_economy`, defaulting to 100, 50, and 20 square feet. From that, `yield_sqft` subtracts each rejected slab at the card's `slab_sqft` (5 by default) and each rejected roll at `roll_sqft` (10 by default). A batch whose `yield_sqft` comes out at zero or below is rejected with `ERR_INVALID_REQUEST`. Every slab and roll that passes QC is sellable, so `sellable_sqft` always equals `yield_sqft`."

    Design: Corner/calculations/pallet_yield_shortfall_arithmetic
    """
    v = _config_variety(api)
    f = create_field(api, v["id"])
    b1 = create_batch(api, f["id"], pallet_count=10, shortfall_slabs=2,
                      shortfall_rolls=1, scheduled_date="2026-08-02")
    assert_money_eq(b1["full_sqft"], 1000, "batch 1 full_sqft")
    assert_money_eq(b1["yield_sqft"], 980, "batch 1 yield_sqft")  # 1000 - 2*5 - 1*10
    assert_money_eq(b1["sellable_sqft"], 980, "sellable equals yield")

    b2 = create_batch(api, f["id"], grade="ECONOMY", pallet_count=3,
                      shortfall_rolls=1, scheduled_date="2026-08-02")
    assert_money_eq(b2["full_sqft"], 60, "batch 2 full_sqft")
    assert_money_eq(b2["yield_sqft"], 50, "batch 2 yield_sqft")  # 60 - 1*10


# ---------------------------------------------------------------------------
# Corner: entities / harvest_batch_invalid_enum_grade_returns_invalid_enum
# ---------------------------------------------------------------------------

def test_harvest_batch_invalid_enum_grade_returns_invalid_enum(api):
    """PRD §2.9: "5. **Enum membership** — `grade`, `settlement_method`, `weather_case`, and payment `method` each carry a declared member; otherwise `ERR_INVALID_ENUM`."
    PRD §3.3: "A `HarvestSupervisor` schedules a harvest batch against a field by supplying the `field_id`, the `grade` (`PREMIUM`, `STANDARD`, or `ECONOMY`), the `pallet_count` (at least one), the QC reject counts `shortfall_slabs` and `shortfall_rolls` (zero or more), a `scheduled_date` no earlier than the clock's current date, and the concurrency token `expected_field_version` of §2.8."

    Design: Corner/entities/harvest_batch_invalid_enum_grade_returns_invalid_enum
    """
    v = _config_variety(api)
    f = create_field(api, v["id"])
    payload = factories.create_harvest_batch_payload(
        f["id"], f["version"], scheduled_date="2026-08-02"
    )
    payload["grade"] = "DELUXE"
    resp = api.create_harvest_batch(payload, HARVEST)
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM, 400)


# ---------------------------------------------------------------------------
# Corner: state_machines / harvest_complete_window_boundary
# ---------------------------------------------------------------------------

def test_harvest_complete_window_boundary(api):
    """PRD §3.3: "When the `HarvestSupervisor` records the actual harvest, the payload's `actual_harvest_start` must fall at or after the card's `harvest_earliest_start_hour` (06:00 by default), `actual_harvest_end` must fall at or before `harvest_latest_end_hour` (18:00 by default), and the end must be strictly later than the start; any violation is rejected with `ERR_HARVEST_WINDOW`."
    PRD §3.3: "On success the batch moves from `PENDING` to `COMPLETE` and the field's `remaining_sqft` drops by the batch's `sellable_sqft` — only completion decrements; a `PENDING` batch never has."

    Design: Corner/state_machines/harvest_complete_window_boundary
    """
    v = _config_variety(api)
    f = create_field(api, v["id"])
    b = create_batch(api, f["id"], pallet_count=5, scheduled_date="2026-08-02")

    resp = api.complete_harvest_batch(
        b["id"],
        factories.complete_harvest_batch_payload(
            actual_harvest_start="2026-08-02T05:30:00Z",
            actual_harvest_end="2026-08-02T06:30:00Z",
        ),
        HARVEST,
    )
    validate_error(resp, ApiErrorId.ERR_HARVEST_WINDOW, 422)
    still = get_success_data(api.get_harvest_batch(b["id"], HARVEST))
    assert still["status"] == "PENDING", "rejected completion must not transition"

    # Start exactly at 06:00 is inside the inclusive window.
    completed = get_success_data(api.complete_harvest_batch(
        b["id"],
        factories.complete_harvest_batch_payload(
            actual_harvest_start="2026-08-02T06:00:00Z",
            actual_harvest_end="2026-08-02T06:30:00Z",
        ),
        HARVEST,
    ))
    assert completed["status"] == "COMPLETE"
    assert_money_eq(get_field(api, f["id"])["remaining_sqft"], 39500,
                    "40000 - 500 sellable")


# ---------------------------------------------------------------------------
# Corner: state_machines / linked_batch_cannot_be_cancelled
# ---------------------------------------------------------------------------

def test_linked_batch_cannot_be_cancelled(api):
    """PRD §3.3: "Cancelling a batch is permitted only while it is `PENDING` and still unlinked to any order; a cancelled batch leaves `remaining_sqft` untouched, keeping the availability accounting conserved."
    PRD §3.6: "Cancelling moves the order to `CANCELLED`, detaches every linked batch (each batch's `order_id` returns to null), releases the booked delivery window back to the zone's truck pool, and moves any crew referral in `REFERRED` or `SCHEDULED` to `REPLACED` with the order's `crew_referral_status` reset to `NONE`."

    Design: Corner/state_machines/linked_batch_cannot_be_cancelled
    """
    bundle = mini_chain(api, stage="confirmed")
    b_id, o_id = bundle["b"]["id"], bundle["o"]["id"]

    linked = get_success_data(api.get_harvest_batch(b_id, HARVEST))
    assert linked["order_id"] == o_id, "batch is linked after confirm"

    resp = api.cancel_harvest_batch(b_id, HARVEST)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    cancelled_order = get_success_data(api.cancel_order(o_id, SALES))
    assert cancelled_order["status"] == "CANCELLED"
    released = get_success_data(api.get_harvest_batch(b_id, HARVEST))
    assert released["order_id"] is None, "order cancel detaches the batch link"

    cancelled_batch = get_success_data(api.cancel_harvest_batch(b_id, HARVEST))
    assert cancelled_batch["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# Corner: cross_cutting / occ_stale_field_version_rejected_then_retry_ok
# ---------------------------------------------------------------------------

def test_occ_stale_field_version_rejected_then_retry_ok(api):
    """PRD §2.8: "Exactly one write is version-guarded. Scheduling a harvest batch requires the request to carry `expected_field_version`, holding the `version` of the target field as the client last observed it. If the field's current `version` has advanced past that value — because an earlier batch creation bumped it, a quality update rewrote the agronomic inputs, or the field was archived — the create is rejected with `ERR_STALE_FIELD_VERSION` (HTTP 412)."
    PRD §2.8: "The rule is purely sequential: a second create carrying an older observed version deterministically fails, regardless of when the two requests were issued."

    Design: Corner/cross_cutting/occ_stale_field_version_rejected_then_retry_ok
    """
    v = _config_variety(api)
    f = create_field(api, v["id"])
    v1 = f["version"]

    payload = factories.create_harvest_batch_payload(
        f["id"], v1, scheduled_date="2026-08-02"
    )
    first = validate_success(api.create_harvest_batch(payload, HARVEST), 201)
    assert first["status"] == "PENDING"

    # Replaying the same observed version deterministically fails.
    stale = api.create_harvest_batch(
        factories.create_harvest_batch_payload(
            f["id"], v1, scheduled_date="2026-08-02"
        ),
        HARVEST,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_FIELD_VERSION, 412)

    v2 = get_field(api, f["id"])["version"]
    assert v2 == v1 + 1, "each batch creation increments the field's version once"
    retry = validate_success(api.create_harvest_batch(
        factories.create_harvest_batch_payload(
            f["id"], v2, scheduled_date="2026-08-02"
        ),
        HARVEST,
    ), 201)
    assert is_valid_uuid(retry["id"])
    assert get_field(api, f["id"])["version"] == v1 + 2


# ---------------------------------------------------------------------------
# Corner: cross_cutting / version_increments_on_each_mutation
# ---------------------------------------------------------------------------

def test_version_increments_on_each_mutation(api):
    """PRD §2.4: "- `version` (integer): a system-managed counter that increments with every modification — state transitions, derived-field writes, and cascading updates that touch the entity all count as modifications."
    PRD §3.2: "A `FarmManager` may later refresh the four agronomic inputs through the field's quality-update operation; that write increments the field's `version`, one of the movements the batch-scheduling guard of §2.8 watches for."
    PRD §3.3: "Creating the batch also increments the field's `version`, which is what makes a strictly later create carrying an older `expected_field_version` fail (§2.8)."

    Design: Corner/cross_cutting/version_increments_on_each_mutation
    """
    v = _config_variety(api)
    f = create_field(api, v["id"])
    v_created = f["version"]

    v_read = get_field(api, f["id"])["version"]
    assert v_read == v_created, "reads never increment the version"

    patched = get_success_data(
        api.update_field_quality(f["id"], {"soil_moisture_pct": 47}, FARM)
    )
    assert patched["version"] == v_created + 1, (
        "the quality update increments the version exactly once"
    )

    get_success_data(api.create_harvest_batch(
        factories.create_harvest_batch_payload(
            f["id"], patched["version"], pallet_count=5,
            scheduled_date="2026-08-02"
        ),
        HARVEST,
    ))
    assert get_field(api, f["id"])["version"] == v_created + 2, (
        "the batch creation bumps the version exactly once more"
    )
