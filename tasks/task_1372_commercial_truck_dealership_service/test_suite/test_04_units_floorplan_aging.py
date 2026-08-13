"""Units: floor-plan ledger, interest accrual, aging buckets, curtailments,
inspection loop, wholesale, and unit OCC (PRD §3.3, §2.7, §2.8)."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated, get_success_data,
    assert_ledger_invariant,
    create_new_unit, create_ready_unit, create_shipped_order, create_slot_pool,
    receive_unit_from_order, set_clock, run_sweep, get_slot,
)

MGR = TEST_USERS["sales_manager_headers"]
SERVICE_MGR = TEST_USERS["service_manager_headers"]
CONTROLLER = TEST_USERS["controller_headers"]


def _get_unit(unit_id):
    return get_success_data(api_client.get_unit(unit_id, CONTROLLER))


def _entries(unit_id):
    entries, _ = validate_paginated(api_client.list_floor_plan_entries(unit_id, CONTROLLER))
    return entries


# ---------------------------------------------------------------- Queue A ---

class TestFloorplanActualVsProjectedPayoff:
    def _setup(self):
        unit = create_ready_unit(vin="1FUJGBDV1CLW88321")
        # 10 days pass with NO sweep: nothing posts to the ledger.
        set_clock("2026-08-25T00:00:00Z")
        return unit

    def test_actual_balance_untouched_while_projection_adds_interest(self, api):
        """PRD §3.3: "This is the *actual accrual* variant — the balance moves
        only when the sweep, a sale, or a wholesale posts entries."
        PRD §3.3: "it projects the same interest formula over the whole days
        from `last_accrual_date` to that date (floored at zero days), then
        quotes `payoff_cents` as the current `floorplan_balance_cents` plus
        `projected_interest_cents` plus `curtailment_due_cents`".

        Design: Difficulty/dual_variant_calc/floorplan_actual_accrual_vs_projected_payoff_quote
        """
        unit = self._setup()
        current = _get_unit(unit["id"])
        assert current["floorplan_balance_cents"] == 10085000
        quote = validate_success(api_client.get_payoff_quote(unit["id"], CONTROLLER), 200)
        # round_half_up(10085000 * 690 / 10000 / 360 * 10)
        assert quote["projected_interest_cents"] == 19330
        assert quote["balance_cents"] == 10085000
        assert quote["curtailment_due_cents"] == 0
        assert quote["payoff_cents"] == 10104330
        assert quote["payoff_cents"] != current["floorplan_balance_cents"]

    def test_payoff_projection_posts_nothing(self, api):
        """PRD §3.3: "The *payoff projection* variant is forward-looking and
        posts nothing: given an optional `as_of_date` (defaulting to the clock
        date), it projects the same interest formula over the whole days from
        `last_accrual_date` to that date (floored at zero days)".
        PRD §3.3: "On a unit with days passed since the last sweep, the
        projection deliberately exceeds the ledger balance until the next
        accrual posts."

        Design: Difficulty/dual_variant_calc/floorplan_actual_accrual_vs_projected_payoff_quote
        """
        unit = self._setup()
        quote = validate_success(api_client.get_payoff_quote(unit["id"], CONTROLLER), 200)
        assert quote["payoff_cents"] > quote["balance_cents"]
        entries = _entries(unit["id"])
        assert len(entries) == 1 and entries[0]["entry_type"] == "ADVANCE"
        assert _get_unit(unit["id"])["floorplan_balance_cents"] == 10085000


class TestAgingBucketDay90Boundary:
    def test_day_90_stays_in_first_bucket(self, api):
        """PRD §3.3: "The `aging_bucket` bands are `B0_90` through day 90,
        `B91_180` for days 91 to 180 ... so day 90 still sits in `B0_90`."
        PRD §3.3: "Scheduled curtailment follows the same clock: nothing
        through day 180 (day 180 still owes zero)".

        Design: Difficulty/boundary_precision_check/aging_bucket_day_90_vs_day_91_boundary
        """
        unit = create_new_unit(vin="1FUJGBDV1CLW88323")
        set_clock("2026-11-13T00:00:00Z")  # exactly 90 days after 2026-08-15
        run_sweep()
        current = _get_unit(unit["id"])
        assert current["days_in_stock"] == 90
        assert current["aging_bucket"] == "B0_90"
        assert current["curtailment_due_cents"] == 0

    def test_day_91_flips_to_second_bucket(self, api):
        """PRD §3.3: "`B91_180` for days 91 to 180".

        Design: Difficulty/boundary_precision_check/aging_bucket_day_90_vs_day_91_boundary
        """
        unit = create_new_unit(vin="1FUJGBDV1CLW88323")
        set_clock("2026-11-14T00:00:00Z")  # 91 days after 2026-08-15
        run_sweep()
        current = _get_unit(unit["id"])
        assert current["days_in_stock"] == 91
        assert current["aging_bucket"] == "B91_180"


class TestFloorplanAdjustmentPairConservation:
    def _setup(self):
        unit = create_ready_unit(vin="1FUJGBDV1CLW88325")
        return _get_unit(unit["id"])

    def test_compensating_adjustments_restore_balance(self, api):
        """PRD §3.3: "A manual adjustment posts a signed `ADJUSTMENT` entry of
        the supplied `amount_cents` with an optional `note`, adds that amount
        to `floorplan_balance_cents`, increments the unit's `version`".

        Design: Difficulty/compensating_invariant/floorplan_adjustment_pair_conserves_ledger_balance
        """
        unit = self._setup()
        v = unit["version"]
        data = validate_success(api_client.create_floor_plan_adjustment(
            unit["id"], {"amount_cents": 50000, "expected_unit_version": v,
                         "note": "damage holdback"}, CONTROLLER), 201)
        assert data["floorplan_balance_cents"] == 10135000
        assert data["version"] == v + 1
        data = validate_success(api_client.create_floor_plan_adjustment(
            unit["id"], {"amount_cents": -50000, "expected_unit_version": v + 1,
                         "note": "holdback released"}, CONTROLLER), 201)
        assert data["floorplan_balance_cents"] == 10085000
        assert data["version"] == v + 2

    def test_ledger_replays_to_conserved_balance(self, api):
        """PRD §2.8: "For each unit the invariant holds that
        `floorplan_balance_cents` equals the signed sum of `amount_cents` over
        all of that unit's `FloorPlanEntry` records."
        PRD §2.8: "a `resulting_balance_cents` giving the running balance after
        that entry in chronological replay order".

        Design: Difficulty/compensating_invariant/floorplan_adjustment_pair_conserves_ledger_balance
        """
        unit = self._setup()
        v = unit["version"]
        api_client.create_floor_plan_adjustment(
            unit["id"], {"amount_cents": 50000, "expected_unit_version": v}, CONTROLLER)
        api_client.create_floor_plan_adjustment(
            unit["id"], {"amount_cents": -50000, "expected_unit_version": v + 1}, CONTROLLER)
        entries = _entries(unit["id"])
        assert [e["entry_type"] for e in entries] == ["ADVANCE", "ADJUSTMENT", "ADJUSTMENT"]
        assert [e["resulting_balance_cents"] for e in entries] == [10085000, 10135000, 10085000]
        assert_ledger_invariant(_get_unit(unit["id"]), entries)


# ---------------------------------------------------------------- Queue B ---

def test_unit_inspect_fail_loop_increments_recondition_count(api):
    """PRD §3.3: "A `PASS` moves the unit to `READY` from any of those states;
    a `FAIL` moves it to `RECONDITIONING` — including from `READY`, and
    including from `RECONDITIONING` itself — and every `FAIL` increments
    `recondition_count` by one."

    Design: Corner/state_machines/unit_inspect_fail_loop_increments_recondition_count
    """
    unit = create_ready_unit(vin="1FUJGBDV1CLW88328")
    d1 = validate_success(api_client.inspect_unit(unit["id"], {"outcome": "FAIL"}, SERVICE_MGR), 200)
    assert d1["status"] == "RECONDITIONING" and d1["recondition_count"] == 1
    d2 = validate_success(api_client.inspect_unit(unit["id"], {"outcome": "FAIL"}, SERVICE_MGR), 200)
    assert d2["status"] == "RECONDITIONING" and d2["recondition_count"] == 2
    d3 = validate_success(api_client.inspect_unit(unit["id"], {"outcome": "PASS"}, SERVICE_MGR), 200)
    assert d3["status"] == "READY" and d3["recondition_count"] == 2


def test_curtailment_payment_posts_entry_and_reduces_balance(api):
    """PRD §3.3: "A curtailment payment posts a `CURTAILMENT` entry of negative
    `amount_cents` with an optional `note`, reducing the balance; the amount
    must be positive, no more than `curtailment_due_cents`, and no more than
    `floorplan_balance_cents`".
    PRD §2.10(4): "Body well-formedness: required fields present, enum values
    valid, numeric ranges valid ... — `ERR_INVALID_REQUEST` (400)."

    Design: Corner/calculations/curtailment_payment_posts_entry_and_reduces_balance
    """
    unit = create_new_unit(vin="1FUJGBDV1CLW88338")
    set_clock("2027-02-12T00:00:00Z")  # day 181
    run_sweep()
    current = _get_unit(unit["id"])
    # Interest posted: round_half_up(10085000 * 690/10000 / 360 * 181) = 349865
    assert current["floorplan_balance_cents"] == 10434865
    assert current["curtailment_due_cents"] == 1008500

    # Over-paying the scheduled curtailment (due + 1 cent) is a bad amount.
    validate_error(api_client.create_floor_plan_curtailment(
        unit["id"], {"amount_cents": 1008501, "note": "over"}, CONTROLLER),
        ApiErrorId.ERR_INVALID_REQUEST)

    data = validate_success(api_client.create_floor_plan_curtailment(
        unit["id"], {"amount_cents": 500000, "note": "partial"}, CONTROLLER), 201)
    assert data["floorplan_balance_cents"] == 9934865
    entries = _entries(unit["id"])
    assert entries[-1]["entry_type"] == "CURTAILMENT"
    assert entries[-1]["amount_cents"] == -500000
    assert entries[-1]["resulting_balance_cents"] == 9934865


def test_curtailment_schedule_day_181_boundary(api):
    """PRD §3.3: "Scheduled curtailment follows the same clock: nothing through
    day 180 (day 180 still owes zero), ten percent of `invoice_cost_cents`
    rounded half-up once the unit reaches day 181, twenty-five percent rounded
    half-up at day 271, and the full invoice cost at day 366."

    Design: Corner/calculations/curtailment_schedule_day_181_boundary
    """
    unit = create_new_unit(vin="1FUJGBDV1CLW88329")
    set_clock("2027-02-11T00:00:00Z")  # day 180
    run_sweep()
    current = _get_unit(unit["id"])
    assert current["days_in_stock"] == 180
    assert current["aging_bucket"] == "B91_180"
    assert current["curtailment_due_cents"] == 0

    set_clock("2027-02-12T00:00:00Z")  # day 181
    run_sweep()
    current = _get_unit(unit["id"])
    assert current["days_in_stock"] == 181
    assert current["aging_bucket"] == "B181_270"
    assert current["curtailment_due_cents"] == 1008500


def test_floor_plan_interest_posts_once_per_sweep_and_is_chronological(api):
    """PRD §3.3: "At each sweep, for each eligible unit, the number of whole
    days since `last_accrual_date` is taken (skipping the unit when that count
    is zero or negative), and one `INTEREST_ACCRUAL` entry posts interest equal
    to the balance times `apr_bp` divided by 10,000, divided by 360, times the
    days elapsed, rounded half-up to integer cents; `last_accrual_date` then
    advances to the clock date."

    Design: Corner/calculations/floor_plan_interest_posts_once_per_sweep_and_is_chronological
    """
    unit = create_new_unit(vin="1FUJGBDV1CLW88330")
    set_clock("2026-08-25T00:00:00Z")
    sweep = run_sweep()
    assert sweep["interest_entries_posted"] == 1
    # Same-day second sweep: zero days elapsed -> unit skipped.
    sweep = run_sweep()
    assert sweep["interest_entries_posted"] == 0
    set_clock("2026-08-30T00:00:00Z")
    sweep = run_sweep()
    assert sweep["interest_entries_posted"] == 1
    current = _get_unit(unit["id"])
    # 10085000 + 19330 (10 days) + 9683 (5 days on 10104330)
    assert current["floorplan_balance_cents"] == 10114013
    assert current["last_accrual_date"] == "2026-08-30"


def test_wholesale_loss_and_payoff_on_aged_unit(api):
    """PRD §3.3: "the same interest-then-payoff sequence clears the floor plan,
    the unit becomes `WHOLESALED`, and `wholesale_loss_cents` records the
    shortfall — the excess of `invoice_cost_cents` over `wholesale_price_cents`,
    floored at zero."

    Design: Corner/calculations/wholesale_loss_and_payoff_on_aged_unit
    """
    unit = create_ready_unit(vin="1FUJGBDV1CLW88331")
    set_clock("2027-09-01T00:00:00Z")  # day 382 -> OVER_365
    run_sweep()
    current = _get_unit(unit["id"])
    assert current["aging_bucket"] == "OVER_365"
    data = validate_success(api_client.wholesale_unit(
        unit["id"], {"wholesale_price_cents": 6000000}, MGR), 200)
    assert data["status"] == "WHOLESALED"
    assert data["wholesale_loss_cents"] == 4085000  # 10085000 - 6000000
    assert data["floorplan_balance_cents"] == 0


def test_wholesale_gate_requires_aged_bucket(api):
    """PRD §3.3: "the unit must be `READY` (`ERR_UNIT_NOT_SELLABLE` otherwise)
    and its `aging_bucket` must be `B181_270`, `B271_365`, or `OVER_365`
    (`ERR_UNIT_NOT_WHOLESALE_ELIGIBLE` otherwise)."

    Design: Corner/validations/wholesale_gate_requires_aged_bucket
    """
    unit = create_ready_unit(vin="1FUJGBDV1CLW88334")
    set_clock("2026-11-14T00:00:00Z")  # day 91 -> B91_180
    run_sweep()
    validate_error(api_client.wholesale_unit(
        unit["id"], {"wholesale_price_cents": 6000000}, MGR),
        ApiErrorId.ERR_UNIT_NOT_WHOLESALE_ELIGIBLE)
    assert _get_unit(unit["id"])["status"] == "READY"


def test_cascading_receive_creates_unit_and_advance_entry(api):
    """PRD §3.2: "The order moves to `DELIVERED`, its `received_unit_id` is
    set, and a new `Unit` is born: `unit_kind` `NEW`, status `IN_STOCK`,
    `invoice_cost_cents` equal to the order's `committed_total_cents`,
    `stocking_date` the current clock date, `floorplan_active` true, `apr_bp`
    captured from the payload (defaulting to 690 basis points — 6.90 percent —
    when omitted)".
    PRD §3.2: "its creation also posts the first ledger entry: an `ADVANCE`
    equal to `invoice_cost_cents`, establishing `floorplan_balance_cents` at
    the invoice cost and `last_accrual_date` at the stocking date."

    Design: Corner/cross_cutting_complexity_layers/cascading_receive_creates_unit_and_advance_entry
    """
    slot = create_slot_pool(build_month="2026-08", capacity=5)
    order = create_shipped_order(slot_id=slot["id"])
    resp = api_client.receive_factory_order(
        order["id"], {"vin": "1FUJGBDV1CLW88337", "apr_bp": 700}, MGR)
    data = validate_success(resp, 200)
    assert data["status"] == "DELIVERED"
    unit_id = data["received_unit_id"]
    assert unit_id
    unit = _get_unit(unit_id)
    assert unit["apr_bp"] == 700
    assert unit["status"] == "IN_STOCK"
    assert unit["stocking_date"] == "2026-08-15"
    entries = _entries(unit_id)
    assert len(entries) == 1
    assert entries[0]["entry_type"] == "ADVANCE"
    assert entries[0]["amount_cents"] == 10085000
    assert entries[0]["entry_date"] == "2026-08-15"
    assert entries[0]["resulting_balance_cents"] == 10085000
    assert unit["floorplan_balance_cents"] == 10085000
    assert unit["last_accrual_date"] == "2026-08-15"


def test_occ_stale_version_rejected_on_floorplan_adjustment(api):
    """PRD §2.7: "a `Controller` posting a manual floor-plan adjustment must
    carry `expected_unit_version` matching the target unit's current
    `version`; the client computed its adjustment from a balance view that the
    ledger may since have moved past, so a mismatch is likewise rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.5: "a `version` integer that increments on every mutation."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_rejected_on_floorplan_adjustment
    """
    unit = create_new_unit(vin="1FUJGBDV1CLW88336")
    stale_version = unit["version"]
    set_clock("2026-08-20T00:00:00Z")
    run_sweep()  # posts 5 days of interest and mutates the unit
    current = _get_unit(unit["id"])
    # round_half_up(10085000 * 690/10000 / 360 * 5) = 9665
    assert current["floorplan_balance_cents"] == 10094665
    assert current["version"] != stale_version

    validate_error(api_client.create_floor_plan_adjustment(
        unit["id"], {"amount_cents": 1000, "expected_unit_version": stale_version,
                     "note": "stale"}, CONTROLLER),
        ApiErrorId.ERR_STALE_VERSION, 412)

    fresh = _get_unit(unit["id"])
    data = validate_success(api_client.create_floor_plan_adjustment(
        unit["id"], {"amount_cents": 1000, "expected_unit_version": fresh["version"],
                     "note": "fresh"}, CONTROLLER), 201)
    assert data["floorplan_balance_cents"] == 10095665
