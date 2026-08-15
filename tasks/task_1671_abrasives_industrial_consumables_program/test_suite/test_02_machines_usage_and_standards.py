"""Machine lifecycle, usage recording, variance surveillance, safety gates."""
import pytest

from test_helpers import (
    ApiErrorId,
    get_lot,
    get_machine,
    get_standard,
    make_lot,
    make_machine,
    make_product,
    make_standard,
    make_usage_record,
    make_usage_scenario,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["program_admin_headers"]
AM = TEST_USERS["account_manager_headers"]
EHS = TEST_USERS["ehs_officer_headers"]


# ---------------------------------------------------------------------------
# Difficulty / non_linear_state_machine / machine_quarantine_reinstate_cycle
# ---------------------------------------------------------------------------


def test_machine_quarantine_reinstate_cycle_statuses(api):
    """PRD §3.2: "Machine safety state is cyclic: an `EHSOfficer` may quarantine
    an `ACTIVE` machine, moving it to `QUARANTINED`, and may later reinstate a
    `QUARANTINED` machine back to `ACTIVE`. There is no terminal state."

    Design: Difficulty/non_linear_state_machine/machine_quarantine_reinstate_cycle
    """
    machine = make_machine(customer_ref="PLANT-4", asset_tag="GR-01")
    assert machine["status"] == "ACTIVE"

    m1 = validate_success(api.quarantine_machine(machine["id"], EHS), 200)
    assert m1["status"] == "QUARANTINED"

    m2 = validate_success(api.reinstate_machine(machine["id"], EHS), 200)
    assert m2["status"] == "ACTIVE"

    # Second quarantine succeeds — the cycle repeats, not a one-way transition.
    m3 = validate_success(api.quarantine_machine(machine["id"], EHS), 200)
    assert m3["status"] == "QUARANTINED"


def test_machine_quarantine_reinstate_cycle_versions(api):
    """PRD §2.5: "`version` (integer): starts at its initial value on creation
    and increments by one on every mutation"

    Design: Difficulty/non_linear_state_machine/machine_quarantine_reinstate_cycle
    """
    machine = make_machine(customer_ref="PLANT-4B", asset_tag="GR-01B")
    v0 = machine["version"]

    m1 = validate_success(api.quarantine_machine(machine["id"], EHS), 200)
    assert m1["version"] == v0 + 1

    m2 = validate_success(api.reinstate_machine(machine["id"], EHS), 200)
    assert m2["version"] == v0 + 2

    m3 = validate_success(api.quarantine_machine(machine["id"], EHS), 200)
    assert m3["version"] == v0 + 3


# ---------------------------------------------------------------------------
# Corner / entities / machine_version_increments_on_mutation
# ---------------------------------------------------------------------------


def test_machine_version_increments_on_mutation(api):
    """PRD §2.5: "`version` (integer): starts at its initial value on creation
    and increments by one on every mutation; it is the anchor for optimistic
    concurrency control (§2.7)."
    PRD §3.2: "an `EHSOfficer` may quarantine an `ACTIVE` machine, moving it to
    `QUARANTINED`"

    Design: Corner/entities/machine_version_increments_on_mutation
    """
    machine = make_machine(customer_ref="PLANT-V", asset_tag="GR-V1")
    v1 = machine["version"]
    m2 = validate_success(api.quarantine_machine(machine["id"], EHS), 200)
    assert m2["status"] == "QUARANTINED"
    assert m2["version"] == v1 + 1, (
        f"quarantine must increment version by exactly 1: {v1} -> {m2['version']}"
    )


# ---------------------------------------------------------------------------
# Corner / state_machines / machine_reinstate_when_active_rejected
# ---------------------------------------------------------------------------


def test_machine_reinstate_when_active_rejected(api):
    """PRD §3.2: "Quarantining a machine that is not `ACTIVE`, or reinstating
    one that is not `QUARANTINED`, is `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/machine_reinstate_when_active_rejected
    """
    machine = make_machine(customer_ref="PLANT-RA", asset_tag="GR-RA")
    resp = api.reinstate_machine(machine["id"], EHS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)


# ---------------------------------------------------------------------------
# Difficulty / cross_entity_state_dependency / usage_record_gated_by_machine_status
# ---------------------------------------------------------------------------


def test_usage_blocked_while_machine_quarantined(api):
    """PRD §3.2: "While a machine is `QUARANTINED`, neither usage records nor
    trials may be created against it; both attempts fail with
    `ERR_MACHINE_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/usage_record_gated_by_machine_status
    """
    scenario = make_usage_scenario(lot_qty=100)
    machine, product, lot = scenario["machine"], scenario["product"], scenario["lot"]

    # Baseline: usage while ACTIVE succeeds.
    ok = make_usage_record(
        machine["id"], product["id"], lot["id"], qty_used=10, parts_produced=500
    )
    assert ok["id"]

    validate_success(api.quarantine_machine(machine["id"], EHS), 200)
    resp = api.create_usage_record(
        {
            "machine_id": machine["id"],
            "product_id": product["id"],
            "lot_id": lot["id"],
            "usage_date": "2026-08-01",
            "qty_used": 10,
            "parts_produced": 500,
        },
        AM,
    )
    validate_error(resp, ApiErrorId.ERR_MACHINE_NOT_ACTIVE.value)


def test_usage_reenabled_after_machine_reinstated(api):
    """PRD §3.2: "Machine safety state is cyclic: an `EHSOfficer` may quarantine
    an `ACTIVE` machine, moving it to `QUARANTINED`, and may later reinstate a
    `QUARANTINED` machine back to `ACTIVE`."
    PRD §3.2: "While a machine is `QUARANTINED`, neither usage records nor
    trials may be created against it; both attempts fail with
    `ERR_MACHINE_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/usage_record_gated_by_machine_status
    """
    scenario = make_usage_scenario(lot_qty=100)
    machine, product, lot = scenario["machine"], scenario["product"], scenario["lot"]

    validate_success(api.quarantine_machine(machine["id"], EHS), 200)
    validate_success(api.reinstate_machine(machine["id"], EHS), 200)

    ok = make_usage_record(
        machine["id"], product["id"], lot["id"], qty_used=5, parts_produced=250
    )
    assert ok["id"], "usage must succeed again after reinstatement"


# ---------------------------------------------------------------------------
# Difficulty / priority_pair_validation_conflict / usage_create_state_beats_safety
# ---------------------------------------------------------------------------


def test_usage_create_state_beats_safety_machine_not_active(api):
    """PRD §2.8: "When several checks could fail on the same request, the API
    evaluates them in a single fixed priority order and reports the **first**
    failure." — with item 6 "State preconditions ... (`ERR_MACHINE_NOT_ACTIVE`,
    `ERR_LOT_NOT_AVAILABLE`, `ERR_CONTRACT_NOT_ACTIVE`, all 409)" evaluated
    before item 7 "Safety and compliance gates — speed rating before guard
    requirement on usage and trials".

    Design: Difficulty/priority_pair_validation_conflict/usage_create_state_beats_safety
    """
    product = make_product(sku="CB-SLOW", name="Low-rated Disc",
                           max_operating_speed_rpm=4000)
    machine = make_machine(customer_ref="PLANT-8", asset_tag="GR-77",
                           spindle_max_rpm=5000, guard_type="FIXED")
    validate_success(api.quarantine_machine(machine["id"], EHS), 200)
    lot = make_lot(product["id"], lot_code="L-SLOW", qty_received=100)

    resp = api.create_usage_record(
        {
            "machine_id": machine["id"],
            "product_id": product["id"],
            "lot_id": lot["id"],
            "usage_date": "2026-08-01",
            "qty_used": 10,
            "parts_produced": 100,
        },
        AM,
    )
    # Both ERR_MACHINE_NOT_ACTIVE (priority 6) and ERR_SPEED_RATING_EXCEEDED
    # (priority 7) conditions hold; the first failure in the fixed order wins.
    validate_error(resp, ApiErrorId.ERR_MACHINE_NOT_ACTIVE.value)


def test_usage_create_state_beats_safety_no_record_no_decrement(api):
    """PRD §3.4: "On acceptance the lot's `qty_on_hand` is decremented" — a
    rejected usage record is not accepted, so no record is created and the lot
    is not decremented.
    PRD §2.8: "When several checks could fail on the same request, the API
    evaluates them in a single fixed priority order and reports the **first**
    failure."

    Design: Difficulty/priority_pair_validation_conflict/usage_create_state_beats_safety
    """
    product = make_product(sku="CB-SLW2", name="Low-rated Disc 2",
                           max_operating_speed_rpm=4000)
    machine = make_machine(customer_ref="PLANT-8B", asset_tag="GR-77B",
                           spindle_max_rpm=5000, guard_type="FIXED")
    validate_success(api.quarantine_machine(machine["id"], EHS), 200)
    lot = make_lot(product["id"], lot_code="L-SLOW2", qty_received=100)

    resp = api.create_usage_record(
        {
            "machine_id": machine["id"],
            "product_id": product["id"],
            "lot_id": lot["id"],
            "usage_date": "2026-08-01",
            "qty_used": 10,
            "parts_produced": 100,
        },
        AM,
    )
    validate_error(resp, ApiErrorId.ERR_MACHINE_NOT_ACTIVE.value)
    assert get_lot(lot["id"])["qty_on_hand"] == 100, (
        "rejected usage must not decrement the lot"
    )


# ---------------------------------------------------------------------------
# Difficulty / combinatorial_formula / usage_variance_rolling_window_trigger
# ---------------------------------------------------------------------------


def _setup_variance_scenario(sku="CB-VAR"):
    scenario = make_usage_scenario(
        standard_qty_per_part=0.0250,
        lot_qty=5000,
        machine_overrides={
            "customer_ref": "PLANT-3",
            "asset_tag": "BS-01",
            "machine_type": "BELT_SANDER",
            "spindle_max_rpm": 5000,
            "guard_type": "NONE",
        },
        product_overrides={"sku": sku, "name": "Coated Disc"},
    )
    return scenario


def test_usage_variance_exactly_plus_10pct_stays_in_band(api):
    """PRD §3.4: "`variance_band` classifies the variance: strictly greater than
    0.10 is `OVER` — a variance of exactly 0.10 stays in band — strictly less
    than negative 0.10 is `UNDER`, and anything in between is `IN_BAND`."
    PRD §3.4: "`variance_pct` is the difference between `actual_qty_per_part`
    and the covering standard's `standard_qty_per_part`, divided by that
    standard, rounded half-up to 4 decimal places."

    Design: Difficulty/combinatorial_formula/usage_variance_rolling_window_trigger
    """
    s = _setup_variance_scenario()
    # 275 / 10000 = 0.0275; (0.0275 - 0.0250) / 0.0250 = 0.1000 exactly.
    rec = make_usage_record(
        s["machine"]["id"], s["product"]["id"], s["lot"]["id"],
        qty_used=275, parts_produced=10000,
    )
    assert rec["variance_pct"] == pytest.approx(0.1000, abs=1e-9), (
        f"variance_pct: {rec['variance_pct']}"
    )
    assert rec["variance_band"] == "IN_BAND", (
        f"exactly +10% must stay IN_BAND under the strictly-greater rule, got "
        f"{rec['variance_band']!r}"
    )


def test_usage_variance_rolling_window_flags_review_and_elevates_machine(api):
    """PRD §3.4: "Surveillance runs on a rolling window: the 5 most recent usage
    records for the same machine-and-product pair, ordered by `usage_date`
    descending and then `created_at` descending, inclusive of the record just
    accepted. When at least 3 of those 5 records are `OVER`, the covering
    standard's `needs_review` becomes true; otherwise it becomes false. The
    machine's `consumption_flag` is then recomputed: it is `ELEVATED` when any
    `ACTIVE` standard on that machine has `needs_review` true, and `NORMAL`
    otherwise."

    Design: Difficulty/combinatorial_formula/usage_variance_rolling_window_trigger
    """
    s = _setup_variance_scenario(sku="CB-VAR2")
    machine, product, lot, standard = (
        s["machine"], s["product"], s["lot"], s["standard"],
    )

    # One IN_BAND record (+10% exactly).
    make_usage_record(machine["id"], product["id"], lot["id"],
                      qty_used=275, parts_produced=10000)
    # Three OVER records: 300/10000 = 0.0300 -> +20% -> OVER.
    last = None
    for _ in range(3):
        last = make_usage_record(machine["id"], product["id"], lot["id"],
                                 qty_used=300, parts_produced=10000)

    assert last["variance_pct"] == pytest.approx(0.2000, abs=1e-9)
    assert last["variance_band"] == "OVER"

    std_after = get_standard(standard["id"])
    assert std_after["needs_review"] is True, (
        f"3 of the last 5 records OVER must set needs_review true: {std_after}"
    )
    machine_after = get_machine(machine["id"])
    assert machine_after["consumption_flag"] == "ELEVATED", (
        f"machine with a flagged ACTIVE standard must be ELEVATED: {machine_after}"
    )


# ---------------------------------------------------------------------------
# Corner / entities / usage_record_immutable_event
# ---------------------------------------------------------------------------


def test_usage_record_immutable_event_shape(api):
    """PRD §2.5: "Two resources are deliberately **append-only events**: a usage
    record and a disposal record each carry only `id` and `created_at`. Both
    `updated_at` and `version` are absent on these two resources, because they
    are never modified after acceptance."
    PRD §3.4: "Usage records are append-only — they carry only `id` and
    `created_at`, and are never mutated."

    Design: Corner/entities/usage_record_immutable_event
    """
    s = make_usage_scenario(standard_qty_per_part=0.0250, lot_qty=100)
    rec = make_usage_record(
        s["machine"]["id"], s["product"]["id"], s["lot"]["id"],
        qty_used=10, parts_produced=400,
    )
    assert "id" in rec and "created_at" in rec
    assert "version" not in rec, "append-only usage record must not expose version"
    assert "updated_at" not in rec, (
        "append-only usage record must not expose updated_at"
    )
    # actual 10/400 == 0.0250 == standard -> variance 0 -> IN_BAND
    assert rec["variance_band"] == "IN_BAND"
    assert get_lot(s["lot"]["id"])["qty_on_hand"] == 90


# ---------------------------------------------------------------------------
# Corner / state_machines / lot_depleted_at_zero_usage
# ---------------------------------------------------------------------------


def test_lot_depleted_at_zero_usage(api):
    """PRD §3.4: "the `qty_used` must not exceed the lot's `qty_on_hand`
    (`ERR_LOT_QTY_EXCEEDED` — consuming exactly the on-hand quantity is allowed
    and depletes the lot)."
    PRD §3.3: "Whenever a decrement leaves `qty_on_hand` at exactly zero, the
    lot transitions from `AVAILABLE` to `DEPLETED`"

    Design: Corner/state_machines/lot_depleted_at_zero_usage
    """
    s = make_usage_scenario(standard_qty_per_part=0.0250, lot_qty=5)
    rec = make_usage_record(
        s["machine"]["id"], s["product"]["id"], s["lot"]["id"],
        qty_used=5, parts_produced=200,
    )
    assert rec["id"], "qty_used == qty_on_hand is allowed (inclusive)"

    lot = get_lot(s["lot"]["id"])
    assert lot["qty_on_hand"] == 0
    assert lot["status"] == "DEPLETED"


# ---------------------------------------------------------------------------
# Corner / validations / usage_missing_covering_standard_rejected
# ---------------------------------------------------------------------------


def test_usage_missing_covering_standard_rejected(api):
    """PRD §3.4: "an `ACTIVE` standard whose half-open window contains the
    `usage_date` must exist for the machine-and-product pair
    (`ERR_NO_COVERING_STANDARD`)"
    PRD §3.4: "The window is **half-open**: `effective_from` is inside it,
    `effective_to` is outside it"

    Design: Corner/validations/usage_missing_covering_standard_rejected
    """
    product = make_product(sku="NC-1", name="No Cover Disc")
    machine = make_machine(customer_ref="PLANT-NC", asset_tag="GR-NC")
    make_standard(
        machine["id"], product["id"],
        operation_name="OLD_OP", standard_qty_per_part=0.0250,
        effective_from="2026-01-01", effective_to="2026-06-01",
    )
    lot = make_lot(product["id"], lot_code="L-NC", qty_received=100)

    resp = api.create_usage_record(
        {
            "machine_id": machine["id"],
            "product_id": product["id"],
            "lot_id": lot["id"],
            "usage_date": "2026-08-01",
            "qty_used": 10,
            "parts_produced": 400,
        },
        AM,
    )
    validate_error(resp, ApiErrorId.ERR_NO_COVERING_STANDARD.value)


# ---------------------------------------------------------------------------
# Corner / validations / usage_date_in_future_rejected
# ---------------------------------------------------------------------------


def test_usage_date_in_future_rejected(api):
    """PRD §3.4: "the `usage_date` must not be after the current logical-clock
    date (`ERR_USAGE_DATE_IN_FUTURE`)"
    PRD §2.4: "At server startup the clock reads exactly `2026-08-01T00:00:00Z`"

    Design: Corner/validations/usage_date_in_future_rejected
    """
    s = make_usage_scenario(lot_qty=100)
    resp = api.create_usage_record(
        {
            "machine_id": s["machine"]["id"],
            "product_id": s["product"]["id"],
            "lot_id": s["lot"]["id"],
            "usage_date": "2026-08-02",
            "qty_used": 10,
            "parts_produced": 400,
        },
        AM,
    )
    validate_error(resp, ApiErrorId.ERR_USAGE_DATE_IN_FUTURE.value)


# ---------------------------------------------------------------------------
# Corner / validations / usage_qty_exceeds_lot_rejected
# ---------------------------------------------------------------------------


def test_usage_qty_exceeds_lot_rejected(api):
    """PRD §3.4: "the `qty_used` must not exceed the lot's `qty_on_hand`
    (`ERR_LOT_QTY_EXCEEDED` — consuming exactly the on-hand quantity is allowed
    and depletes the lot)."

    Design: Corner/validations/usage_qty_exceeds_lot_rejected
    """
    s = make_usage_scenario(lot_qty=5)
    resp = api.create_usage_record(
        {
            "machine_id": s["machine"]["id"],
            "product_id": s["product"]["id"],
            "lot_id": s["lot"]["id"],
            "usage_date": "2026-08-01",
            "qty_used": 6,
            "parts_produced": 200,
        },
        AM,
    )
    validate_error(resp, ApiErrorId.ERR_LOT_QTY_EXCEEDED.value)
    assert get_lot(s["lot"]["id"])["qty_on_hand"] == 5, "rejected usage must not decrement"


# ---------------------------------------------------------------------------
# Corner / validations / usage_lot_blocked_rejected
# ---------------------------------------------------------------------------


def test_usage_lot_blocked_rejected(api):
    """PRD §3.4: "the lot must exist, must belong to the referenced product (a
    mismatch is `ERR_INVALID_REQUEST`), and must be `AVAILABLE`
    (`ERR_LOT_NOT_AVAILABLE` — `BLOCKED`, `EXPIRED`, and `DEPLETED` lots cannot
    be consumed)"
    PRD §3.1: "**Fan-out — lots.** Every inventory lot in `AVAILABLE` stocking
    the discontinued product moves to `BLOCKED`."

    Design: Corner/validations/usage_lot_blocked_rejected
    """
    p1 = make_product(sku="LB-1", name="Blocked Lot Disc")
    p2 = make_product(sku="LB-2", name="Blocked Lot Repl", max_operating_speed_rpm=6500)
    machine = make_machine(customer_ref="PLANT-LB", asset_tag="GR-LB")
    lot = make_lot(p1["id"], lot_code="L-LB", qty_received=10)
    validate_success(
        api.discontinue_product(p1["id"], {"replacement_product_id": p2["id"]}, ADMIN),
        200,
    )
    assert get_lot(lot["id"])["status"] == "BLOCKED"

    resp = api.create_usage_record(
        {
            "machine_id": machine["id"],
            "product_id": p1["id"],
            "lot_id": lot["id"],
            "usage_date": "2026-08-01",
            "qty_used": 5,
            "parts_produced": 200,
        },
        AM,
    )
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_AVAILABLE.value)


# ---------------------------------------------------------------------------
# Corner / validations / usage_speed_equal_boundary_allowed
# ---------------------------------------------------------------------------


def test_usage_speed_equal_boundary_allowed(api):
    """PRD §3.2: "The **speed gate** requires the product's
    `max_operating_speed_rpm` to be at least the machine's `spindle_max_rpm`;
    a product rated slower than the spindle is rejected with
    `ERR_SPEED_RATING_EXCEEDED`."

    Design: Corner/validations/usage_speed_equal_boundary_allowed
    """
    pa = make_product(sku="SE-A", name="Speed Equal Disc", max_operating_speed_rpm=5000)
    machine = make_machine(customer_ref="PLANT-SE", asset_tag="GR-SE",
                           spindle_max_rpm=5000, guard_type="FIXED")
    make_standard(machine["id"], pa["id"], standard_qty_per_part=0.0250,
                  effective_from="2026-01-01")
    lot = make_lot(pa["id"], lot_code="L-SEA", qty_received=100)

    rec = make_usage_record(machine["id"], pa["id"], lot["id"],
                            qty_used=10, parts_produced=400)
    assert rec["id"], "product rated exactly at spindle max (5000 >= 5000) is allowed"


def test_usage_speed_one_rpm_under_rejected(api):
    """PRD §3.2: "The **speed gate** requires the product's
    `max_operating_speed_rpm` to be at least the machine's `spindle_max_rpm`;
    a product rated slower than the spindle is rejected with
    `ERR_SPEED_RATING_EXCEEDED`."

    Design: Corner/validations/usage_speed_equal_boundary_allowed
    """
    pb = make_product(sku="SE-B", name="Speed Under Disc", max_operating_speed_rpm=4999)
    machine = make_machine(customer_ref="PLANT-SE2", asset_tag="GR-SE2",
                           spindle_max_rpm=5000, guard_type="FIXED")
    lot = make_lot(pb["id"], lot_code="L-SEB", qty_received=100)

    resp = api.create_usage_record(
        {
            "machine_id": machine["id"],
            "product_id": pb["id"],
            "lot_id": lot["id"],
            "usage_date": "2026-08-01",
            "qty_used": 10,
            "parts_produced": 400,
        },
        AM,
    )
    validate_error(resp, ApiErrorId.ERR_SPEED_RATING_EXCEEDED.value)


# ---------------------------------------------------------------------------
# Corner / validations / usage_guard_required_bonded_rejected
# ---------------------------------------------------------------------------


def test_usage_guard_required_bonded_rejected(api):
    """PRD §3.2: "The **guard gate** requires any `BONDED` product to run only
    on a machine whose `guard_type` is `FIXED` or `ADJUSTABLE`; a bonded product
    on an unguarded (`NONE`) machine is rejected with `ERR_GUARD_REQUIRED`."

    Design: Corner/validations/usage_guard_required_bonded_rejected
    """
    product = make_product(sku="GD-1", name="Guard Wheel", product_form="BONDED",
                           max_operating_speed_rpm=6000, shelf_life_months=12)
    machine = make_machine(customer_ref="PLANT-GD", asset_tag="GR-GD",
                           spindle_max_rpm=5000, guard_type="NONE")
    lot = make_lot(product["id"], lot_code="L-GD", manufacture_date="2026-06-01",
                   qty_received=100)

    resp = api.create_usage_record(
        {
            "machine_id": machine["id"],
            "product_id": product["id"],
            "lot_id": lot["id"],
            "usage_date": "2026-08-01",
            "qty_used": 5,
            "parts_produced": 200,
        },
        AM,
    )
    validate_error(resp, ApiErrorId.ERR_GUARD_REQUIRED.value)


# ---------------------------------------------------------------------------
# Difficulty / resource_temporal_overlap / standard_window_half_open_overlap_rule
# ---------------------------------------------------------------------------


def test_standard_window_adjacency_allowed(api):
    """PRD §3.4: "The window is **half-open**: `effective_from` is inside it,
    `effective_to` is outside it, and a null `effective_to` means the standard
    is open-ended. ... Among `ACTIVE` standards for the same machine-and-product
    pair, windows must not overlap; adjacency — one standard's `effective_to`
    equal to another's `effective_from` — is allowed."

    Design: Difficulty/resource_temporal_overlap/standard_window_half_open_overlap_rule
    """
    product = make_product(sku="CB-SW", name="Coated Belt SW")
    machine = make_machine(customer_ref="PLANT-13", asset_tag="GR-13",
                           machine_type="BENCH_GRINDER", spindle_max_rpm=4000)
    s1 = make_standard(machine["id"], product["id"], operation_name="S1",
                       standard_qty_per_part=0.0100,
                       effective_from="2026-01-01", effective_to="2026-07-01")
    assert s1["status"] == "ACTIVE"

    # Adjacent: new.from == S1.to — allowed under half-open semantics.
    s2 = make_standard(machine["id"], product["id"], operation_name="S2",
                       standard_qty_per_part=0.0120, effective_from="2026-07-01")
    assert s2["status"] == "ACTIVE"


def test_standard_window_overlap_rejected(api):
    """PRD §3.4: "Among `ACTIVE` standards for the same machine-and-product
    pair, windows must not overlap; adjacency — one standard's `effective_to`
    equal to another's `effective_from` — is allowed. An overlapping create is
    rejected with `ERR_STANDARD_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/standard_window_half_open_overlap_rule
    """
    product = make_product(sku="CB-SW3", name="Coated Belt SW3")
    machine = make_machine(customer_ref="PLANT-13B", asset_tag="GR-13B",
                           machine_type="BENCH_GRINDER", spindle_max_rpm=4000)
    make_standard(machine["id"], product["id"], operation_name="S1",
                  standard_qty_per_part=0.0100,
                  effective_from="2026-01-01", effective_to="2026-07-01")

    resp = api.create_standard(
        {
            "machine_id": machine["id"],
            "product_id": product["id"],
            "operation_name": "S3",
            "standard_qty_per_part": 0.0110,
            "effective_from": "2026-06-30",
            "effective_to": "2026-12-01",
        },
        AM,
    )
    validate_error(resp, ApiErrorId.ERR_STANDARD_WINDOW_OVERLAP.value)


# ---------------------------------------------------------------------------
# Corner / validations / window_shape_invalid_rejected
# ---------------------------------------------------------------------------


def test_standard_empty_window_rejected(api):
    """PRD §2.8 item 3: "window shape (a trial's `scheduled_end` on or after its
    `scheduled_start`; a standard's `effective_to` strictly after its
    `effective_from` when present)"

    Design: Corner/validations/window_shape_invalid_rejected
    """
    product = make_product(sku="WS-1", name="Window Shape Disc")
    machine = make_machine(customer_ref="PLANT-WS", asset_tag="GR-WS")
    resp = api.create_standard(
        {
            "machine_id": machine["id"],
            "product_id": product["id"],
            "operation_name": "BADWIN",
            "standard_qty_per_part": 0.0250,
            "effective_from": "2026-06-01",
            "effective_to": "2026-06-01",
        },
        AM,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
