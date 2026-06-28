"""Livestock batch lifecycle: parallel health/sale dimensions, quarantine
preconditions, mortality condemnation boundary, and state-vs-safety precedence."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
    create_livestock_batch_payload, record_mortality_payload,
    make_store, make_batch, set_clock,
)

INVMGR = TEST_USERS["inventory_manager_headers"]
KEEPER = TEST_USERS["livestock_keeper_headers"]


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / parallel dimensions
# ---------------------------------------------------------------------------
def test_clear_quarantine_then_list_on_floor_parallel_dimensions(api):
    """PRD §3.3: "Live animals enter the system as batches, governed by two
    independent, parallel state dimensions: a health dimension (`health_state`)
    and a sale dimension (`sale_state`)."
    PRD §3.3: "Clearing quarantine moves a batch's health from `QUARANTINE` to
    `HEALTHY`."
    PRD §3.4: "Listing a batch on the floor advances its sale from `HELD` to
    `ON_FLOOR`".

    Design: Difficulty/non_linear_state_machine/livestock_batch_parallel_health_and_sale_dimensions
    """
    store = make_store()
    batch = make_batch(
        store["id"], head_count=6, unit_price_cents=8000,
        species="gecko", animal_class="REPTILE",
    )
    assert batch["health_state"] == "QUARANTINE"
    assert batch["sale_state"] == "HELD"
    set_clock("2026-01-10T00:00:00Z")
    cleared = validate_success(api.clear_quarantine(batch["id"], KEEPER), 200)
    # Clearing quarantine moves health to HEALTHY but leaves sale at HELD.
    assert cleared["health_state"] == "HEALTHY"
    assert cleared["sale_state"] == "HELD"
    listed = validate_success(api.list_on_floor(batch["id"], KEEPER), 200)
    # Listing moves sale to ON_FLOOR while health stays HEALTHY.
    assert listed["health_state"] == "HEALTHY"
    assert listed["sale_state"] == "ON_FLOOR"


def test_parallel_dimensions_final_states(api):
    """PRD §3.3: "On intake, `health_state` is `QUARANTINE`, `sale_state` is
    `HELD`, and `mortality_count` is zero."
    PRD §3.4: "the `LivestockKeeper` doing so succeeds only when the batch's sale
    is currently `HELD` (otherwise `ERR_BATCH_SALE_STATE_INVALID`) and the
    batch's `health_state` is `HEALTHY`".

    Design: Difficulty/non_linear_state_machine/livestock_batch_parallel_health_and_sale_dimensions
    """
    store = make_store()
    batch = make_batch(
        store["id"], head_count=6, unit_price_cents=8000,
        species="gecko", animal_class="REPTILE",
    )
    set_clock("2026-01-10T00:00:00Z")
    api.clear_quarantine(batch["id"], KEEPER)
    final = validate_success(api.list_on_floor(batch["id"], KEEPER), 200)
    assert final["health_state"] == "HEALTHY"
    assert final["sale_state"] == "ON_FLOOR"


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / mortality condemn rate
# ---------------------------------------------------------------------------
def test_mortality_exactly_half_condemns(api):
    """PRD §3.3: "If that ratio is at least 0.5 — the boundary is inclusive, so a
    ratio of exactly 0.5 condemns — the batch is condemned: `health_state`
    becomes `CONDEMNED` and, because a condemned batch can no longer be sold,
    `sale_state` becomes `SOLD_OUT`."

    Design: Difficulty/boundary_precision_check/mortality_condemn_rate_exactly_half_condemns
    """
    store = make_store()
    batch = make_batch(
        store["id"], head_count=10, unit_price_cents=500, species="molly",
    )
    res = api.record_mortality(batch["id"], record_mortality_payload(5), KEEPER)
    updated = validate_success(res, 200)
    assert updated["health_state"] == "CONDEMNED"
    assert updated["sale_state"] == "SOLD_OUT"
    assert updated["mortality_count"] == 5


def test_mortality_below_half_under_treatment(api):
    """PRD §3.3: "This is a real-number division. If that ratio is at least 0.5 ...
    the batch is condemned ... Otherwise the batch's health becomes
    `UNDER_TREATMENT`."

    Design: Difficulty/boundary_precision_check/mortality_condemn_rate_exactly_half_condemns
    """
    store = make_store()
    batch = make_batch(
        store["id"], head_count=10, unit_price_cents=500, species="molly",
    )
    # 4/10 = 0.4 < 0.5 → UNDER_TREATMENT, not condemned.
    res = api.record_mortality(batch["id"], record_mortality_payload(4), KEEPER)
    updated = validate_success(res, 200)
    assert updated["health_state"] == "UNDER_TREATMENT"
    assert updated["mortality_count"] == 4


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / state beats health-safety
# ---------------------------------------------------------------------------
def test_list_on_floor_sold_out_condemned_returns_state_error(api):
    """PRD §3.4: "Listing a batch on the floor advances its sale from `HELD` to
    `ON_FLOOR`; the `LivestockKeeper` doing so succeeds only when the batch's
    sale is currently `HELD` (otherwise `ERR_BATCH_SALE_STATE_INVALID`) and the
    batch's `health_state` is `HEALTHY` (otherwise `ERR_BATCH_NOT_HEALTHY`)".
    PRD §2.6: "Eighth, the target resource's state must permit the requested
    transition (`ERR_..._STATE_INVALID` or the relevant state error). ... Only
    after all of these do the deeper, operation-specific business rules
    (temporal gates, safety gates, capacity, fiscal sufficiency) run."

    Design: Difficulty/priority_pair_validation_conflict/batch_state_beats_health_safety_on_list_on_floor
    """
    store = make_store()
    batch = make_batch(
        store["id"], head_count=10, unit_price_cents=500, species="guppy",
    )
    # 5/10 = 0.5 condemns: health CONDEMNED, sale SOLD_OUT (both gates fail).
    api.record_mortality(batch["id"], record_mortality_payload(5), KEEPER)
    res = api.list_on_floor(batch["id"], KEEPER)
    # State check (sale != HELD) wins over health-safety check.
    validate_error(res, ApiErrorId.ERR_BATCH_SALE_STATE_INVALID)


def test_list_on_floor_condemned_under_treatment_then_condemn_state_error(api):
    """PRD §3.4: "the `LivestockKeeper` doing so succeeds only when the batch's
    sale is currently `HELD` (otherwise `ERR_BATCH_SALE_STATE_INVALID`) and the
    batch's `health_state` is `HEALTHY` (otherwise `ERR_BATCH_NOT_HEALTHY`)".
    PRD §3.3: "A `LivestockKeeper` may also condemn an under-treatment batch
    outright: a batch whose health is `UNDER_TREATMENT` ... is moved to
    `CONDEMNED` health with its `sale_state` forced to `SOLD_OUT`".

    Design: Difficulty/priority_pair_validation_conflict/batch_state_beats_health_safety_on_list_on_floor
    """
    store = make_store()
    batch = make_batch(
        store["id"], head_count=10, unit_price_cents=500, species="guppy",
    )
    # Drive to UNDER_TREATMENT (1/10 < 0.5), then condemn outright →
    # CONDEMNED health + SOLD_OUT sale. Both list-on-floor gates now fail.
    api.record_mortality(batch["id"], record_mortality_payload(1), KEEPER)
    api.condemn_batch(batch["id"], KEEPER)
    res = api.list_on_floor(batch["id"], KEEPER)
    # Sale-state check (not HELD) is evaluated before the health-safety gate.
    validate_error(res, ApiErrorId.ERR_BATCH_SALE_STATE_INVALID)


# ---------------------------------------------------------------------------
# Corner: state_machines precondition enforcement
# ---------------------------------------------------------------------------
def test_clear_quarantine_before_window_elapsed_rejected(api):
    """PRD §3.3: "when the logical clock has reached at least `intake_at` plus
    `quarantine_days` — a closed lower bound, so the instant exactly equal to
    `intake_at` plus `quarantine_days` qualifies (otherwise
    `ERR_QUARANTINE_NOT_ELAPSED`)".
    PRD §2.11: "At server startup the clock reads exactly
    `2026-01-01T00:00:00Z`".

    Design: Corner/state_machines/clear_quarantine_before_window_elapsed_rejected
    """
    store = make_store()
    batch = make_batch(
        store["id"], head_count=5, unit_price_cents=500, species="betta",
    )
    # Clock left at the default 2026-01-01, which is before intake_at + 5 days.
    res = api.clear_quarantine(batch["id"], KEEPER)
    validate_error(res, ApiErrorId.ERR_QUARANTINE_NOT_ELAPSED)


def test_under_treatment_recovery_clearance_succeeds(api):
    """PRD §3.3: "The same clear-quarantine capability also serves as the
    recovery path for a treated batch: a batch whose health is `UNDER_TREATMENT`
    may return to `HEALTHY` through it. In that recovery case the precondition is
    that the batch is in `UNDER_TREATMENT` health ... and that its mortality
    ratio — `mortality_count` divided by `head_count` — remains strictly below
    the condemnation rate of 0.5 (otherwise `ERR_QUARANTINE_MORTALITY_BLOCK`); on
    success the batch returns to `HEALTHY`".

    Design: Corner/state_machines/quarantine_clearance_blocked_by_mortality
    """
    store = make_store()
    batch = make_batch(
        store["id"], head_count=10, unit_price_cents=500, species="molly",
    )
    # 2/10 = 0.2 < 0.5 → UNDER_TREATMENT.
    api.record_mortality(batch["id"], record_mortality_payload(2), KEEPER)
    res = api.clear_quarantine(batch["id"], KEEPER)
    recovered = validate_success(res, 200)
    assert recovered["health_state"] == "HEALTHY"
