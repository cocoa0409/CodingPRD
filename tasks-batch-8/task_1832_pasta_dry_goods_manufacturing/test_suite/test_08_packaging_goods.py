"""Packaging and finished goods: pinned case-plan rounding, partial-case
boundary, label verification policy, goods-lot creation, release state gate."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_run,
    assert_case_plan_invariant,
    assert_packaging_job,
    capture_new_row,
    complete_packaging,
    create_line,
    create_mounted_die,
    drive_run_to_drying,
    finish_and_confirm_session,
    get_goods_lot,
    get_packaging_job,
    list_goods_lots,
    list_packaging_jobs,
    row_ids,
    schedule_run,
    set_clock,
    setup_completed_run_with_goods_lot,
    setup_run_in_packaging,
    setup_run_world,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

QAM = TEST_USERS["qa_manager_headers"]
OP = TEST_USERS["production_operator_headers"]
CLERK = TEST_USERS["warehouse_clerk_headers"]


def _drive_pair_to_confirmed(recipe_id, lot_id):
    """Two runs on two lines, both DRYING-CONFIRMED at the STANDARD 18h mark."""
    line1 = create_line("L-PB1")
    create_mounted_die(line1["id"], "D-PB1", "LONG_CUT", 100000.0)
    line2 = create_line("L-PB2")
    create_mounted_die(line2["id"], "D-PB2", "LONG_CUT", 100000.0)
    run_a = schedule_run(recipe_id, line1["id"], lot_id, 2000.0)
    run_b = schedule_run(recipe_id, line2["id"], lot_id, 2000.0)
    set_clock("2026-08-10T00:00:00Z")
    sess_a = drive_run_to_drying(run_a)
    sess_b = drive_run_to_drying(run_b)
    set_clock("2026-08-10T18:00:00Z")
    finish_and_confirm_session(sess_a["id"], "2026-08-10T18:00:00Z", 12.0)
    finish_and_confirm_session(sess_b["id"], "2026-08-10T18:00:00Z", 12.0)
    return run_a, run_b


class TestCasePlanPinnedRounding:
    def _setup_packaging_1001(self):
        sc = setup_run_in_packaging(contract_code="C-PKG", lot_weight_kg=3000.0,
                                    planned_input_kg=2000.0,
                                    actual_yield_kg=1001.0)
        return sc

    def test_weight_cap_then_partial_then_pallet_rounding(self, api):
        """PRD: "Second, the effective `units_per_case` is the smaller of the
        recipe's nominal `units_per_case` and the floor of `case_weight_limit_kg`
        times one thousand divided by `unit_weight_g`"
        PRD: "Fifth, `case_count` is the full cases plus the partial case, and
        `pallet_count` is the ceiling of `case_count` divided by the recipe's
        `cases_per_pallet`."

        Design: Difficulty/combinatorial_formula/case_plan_weight_cap_then_partial_then_pallet_rounding
        """
        sc = self._setup_packaging_1001()
        job = sc["job"]
        assert_packaging_job(job)
        assert job["total_units"] == 2002, "floor(1001.0 * 1000 / 500)"
        assert job["units_per_case"] == 24, "weight cap binds below nominal 30"
        assert job["full_case_count"] == 83
        assert job["partial_case_count"] == 1, "remainder 10 >= 6, BRANDED"
        assert job["scrapped_units"] == 0
        assert job["case_count"] == 84
        assert job["pallet_count"] == 3, "ceil(84 / 40)"

    def test_case_plan_persists_and_conserves_units_on_readback(self, api):
        """PRD: "The invariant `total_units` equals cased units plus scrapped
        units holds at every step."
        PRD: "First, `total_units` is the floor of `actual_yield_kg` times one
        thousand divided by the recipe's `unit_weight_g`."

        Design: Difficulty/combinatorial_formula/case_plan_weight_cap_then_partial_then_pallet_rounding
        """
        sc = self._setup_packaging_1001()
        job = get_packaging_job(sc["job"]["id"])
        assert job["total_units"] == 2002
        assert job["units_per_case"] == 24
        assert job["full_case_count"] == 83 and job["partial_case_count"] == 1
        assert_case_plan_invariant(job)
        assert 83 * 24 + 10 + 0 == 2002


def test_packaging_partial_case_minimum_unit_boundary(api):
    """PRD: "Fourth, `partial_case_count` is exactly 1 when the run is
    `BRANDED` and the remainder is at least 6 units, and 0 otherwise;
    `scrapped_units` is the remainder when no partial case is formed and 0 when
    one is"

    Design: Corner/calculations/packaging_partial_case_minimum_unit_boundary
    """
    world = setup_run_world(contract_code="C-PB", lot_weight_kg=5000.0)
    run_a, run_b = _drive_pair_to_confirmed(world["recipe"]["id"], world["lot"]["id"])

    before_a = row_ids(list_packaging_jobs())
    advance_run(run_a["id"], {"actual_yield_kg": 998.5})
    job_a = capture_new_row(list_packaging_jobs, before_a, "packaging job")
    before_b = row_ids(list_packaging_jobs())
    advance_run(run_b["id"], {"actual_yield_kg": 999.0})
    job_b = capture_new_row(list_packaging_jobs, before_b, "packaging job")

    # yield 998.5 -> 1997 units = 83*24 + 5: remainder below the floor scraps
    assert job_a["total_units"] == 1997
    assert job_a["full_case_count"] == 83
    assert job_a["partial_case_count"] == 0
    assert job_a["scrapped_units"] == 5
    assert job_a["case_count"] == 83

    # yield 999.0 -> 1998 units = 83*24 + 6: remainder at the floor cases
    assert job_b["total_units"] == 1998
    assert job_b["full_case_count"] == 83
    assert job_b["partial_case_count"] == 1
    assert job_b["scrapped_units"] == 0
    assert job_b["case_count"] == 84


def test_label_verification_gate_private_label(api):
    """PRD: "a private-label job must have reached `LABEL_VERIFIED` first
    (`ERR_LABEL_VERIFICATION_REQUIRED`), while a branded job may complete
    directly from `CREATED`"
    PRD: "Verification moves the job to `LABEL_VERIFIED` and records
    `labels_verified_by_user_id`."
    PRD: "private-label runs always scrap the remainder, since retailers
    accept full cases only"

    Design: Corner/errors/label_verification_gate_private_label
    """
    sc = setup_run_in_packaging(
        contract_code="C-LVG", actual_yield_kg=400.0,
        recipe_overrides={"recipe_name": "Acme LVG", "brand_type": "PRIVATE_LABEL",
                          "customer_name": "Acme Retail",
                          "min_remaining_shelf_life_pct": 0.5},
    )
    job = sc["job"]

    resp1 = api.complete_packaging_job(job["id"], OP)
    validate_error(resp1, ApiErrorId.ERR_LABEL_VERIFICATION_REQUIRED)

    verified = validate_success(api.verify_labels(job["id"], QAM))
    assert verified["status"] == "LABEL_VERIFIED"
    assert verified["labels_verified_by_user_id"] == "qa-mgr-1"

    completed = validate_success(api.complete_packaging_job(job["id"], OP))
    assert completed["status"] == "COMPLETED"
    assert completed["total_units"] == 800
    assert completed["full_case_count"] == 33
    assert completed["partial_case_count"] == 0, "private label scraps the remainder"
    assert completed["scrapped_units"] == 8

    lots = list_goods_lots()
    assert len(lots) == 1, "completion created exactly one goods lot"

    resp2 = api.complete_packaging_job(job["id"], OP)
    validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)


def test_verify_labels_on_branded_job_rejected(api):
    """PRD: "A `QAManager` verifies labels on a job in `CREATED`, but only when
    the run's `brand_type` is `PRIVATE_LABEL` — the action on a branded job is
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/verify_labels_on_branded_job_rejected
    """
    sc = setup_run_in_packaging(contract_code="C-VLB", actual_yield_kg=400.0)
    assert sc["run"]["brand_type"] == "BRANDED"

    resp = api.verify_labels(sc["job"]["id"], QAM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_packaging_complete_creates_goods_lot(api):
    """PRD: "Completion moves the job to `COMPLETED` and creates the run's
    `FinishedGoodsLot` in `CREATED` with `case_count`, `pallet_count`, and
    `unit_count` taken from the job"
    PRD: "The run stamps `completed_at`, and its finished-goods lots take
    `production_date` as the clock's current date with `expiry_date` computed
    from the recipe's `shelf_life_days`."

    Design: Corner/endpoints/packaging_complete_creates_goods_lot
    """
    sc = setup_run_in_packaging(contract_code="C-PCG", actual_yield_kg=400.0)
    job = sc["job"]

    before = row_ids(list_goods_lots())
    complete_packaging(job["id"])
    goods = capture_new_row(list_goods_lots, before, "finished goods lot")
    assert goods["status"] == "CREATED"
    assert goods["case_count"] == 34, "33 full + 1 partial (remainder 8 >= 6)"
    assert goods["pallet_count"] == 1
    assert goods["unit_count"] == 800, "33*24 + 8 partial"
    assert goods.get("production_date") is None, "stamped only at run completion"

    advance_run(sc["run"]["id"])  # PACKAGING -> COMPLETED at clock 2026-08-10T18:00
    after = get_goods_lot(goods["id"])
    assert after["production_date"] == "2026-08-10"
    assert after["expiry_date"] == "2027-08-10", "production_date + 365 days"


def test_goods_lot_release_before_putaway_rejected(api):
    """PRD: "Release of a stored lot is a `WarehouseClerk` action gated by four
    conditions"
    PRD: "then transition legality on the target resource as
    `ERR_INVALID_STATE`"

    Design: Corner/errors/goods_lot_release_before_putaway_rejected
    """
    sc = setup_completed_run_with_goods_lot(contract_code="C-RBP",
                                            actual_yield_kg=400.0)
    goods = sc["goods_lot"]
    assert goods["status"] == "CREATED"

    resp = api.release_goods_lot(goods["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
