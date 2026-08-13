"""Grinding batches and the pool-return-to-grinding cascade."""
import pytest

from test_helpers import (
    SALES,
    YARD,
    ApiErrorId,
    api_client,
    create_grinding_batch,
    create_scrap_cores,
    create_sorting_batch_with_cores,
    get_core,
    get_customer,
    grade_pool_return,
    log_pool_return,
    setup_delivered_customer,
    setup_sellable_world,
    sort_core,
    validate_error,
    validate_paginated,
    validate_success,
)


def _list_grinding_queued_scrap_cores():
    resp = api_client.list_core_units(
        YARD, params={"grade": "SCRAP", "processing_status": "GRINDING_QUEUED"})
    data, meta = validate_paginated(resp)
    return data, meta


class TestGrindingYield:

    def test_grinding_yield_ratio_four_decimals(self):
        """PRD §3.9: "Completion computes the `yield_ratio` as
        `output_fiber_cuyd` divided by `input_count`, rounded half-up to 4
        decimal places, and moves every input core's `processing_status` to
        terminal `GROUND`, ending the material's journey through the yard."
        PRD §3.9: "the batch captures `input_count` as the number of
        identifiers at creation and starts `QUEUED`."

        Design: Corner/calculations/grinding_yield_precision_four_decimals
        """
        _batch, cores = create_scrap_cores(8)
        gb = create_grinding_batch([c["id"] for c in cores])
        assert gb["input_count"] == 8
        start_resp = api_client.start_grinding_batch(gb["id"], YARD)
        validate_success(start_resp)
        resp = api_client.complete_grinding_batch(
            gb["id"], {"output_fiber_cuyd": 12.5, "revenue_cents": 9000}, YARD)
        done = validate_success(resp)
        assert done["status"] == "COMPLETED"
        # 12.5 / 8 = 1.5625 exactly at 4 decimal places
        assert done["yield_ratio"] == pytest.approx(1.5625, abs=1e-9), (
            f"yield_ratio must be 1.5625, got {done['yield_ratio']}"
        )
        for core in cores:
            after = get_core(core["id"])
            assert after["processing_status"] == "GROUND", (
                f"input core {core['id']} must end GROUND, "
                f"got {after['processing_status']}"
            )

    def test_grind_start_with_non_scrap_core_rejected(self):
        """PRD §3.9: "Starting the grind requires `QUEUED` status (else
        `ERR_GRIND_NOT_QUEUED`) and verifies grindability: every core named in
        `input_core_ids` must hold `grade` `SCRAP` and `processing_status`
        `GRINDING_QUEUED`, else `ERR_CORE_NOT_GRINDABLE`."

        Design: Corner/endpoints/grind_start_rejects_non_scrap_input
        """
        batch, cores = create_sorting_batch_with_cores(
            supplier_name="MixCo", agreed_unit_price_cents=100,
            manifest_count=2,
            estimated_grade_mix={"A": 0.5, "B": 0.0, "SCRAP": 0.5},
            num_cores=2)
        core_a = sort_core(cores[0]["id"], "A")
        core_s = sort_core(cores[1]["id"], "SCRAP", condition_notes="broken")
        gb = create_grinding_batch([core_a["id"], core_s["id"]])
        resp = api_client.start_grinding_batch(gb["id"], YARD)
        validate_error(resp, ApiErrorId.ERR_CORE_NOT_GRINDABLE)
        assert resp.status_code == 422
        after_gb = validate_success(
            api_client.get_grinding_batch(gb["id"], YARD))
        assert after_gb["status"] == "QUEUED", (
            f"rejected start must leave the batch QUEUED, "
            f"got {after_gb['status']}"
        )
        after_a = get_core(core_a["id"])
        after_s = get_core(core_s["id"])
        assert after_a["processing_status"] == "YARD"
        assert after_s["processing_status"] == "GRINDING_QUEUED"


class TestPoolCreditToGrindingCascade:

    def _setup_scrap_return_ready_to_credit(self):
        """Customer with 5 delivered pallets; 2-unit SCRAP return GRADED."""
        spec, _lot, _c = setup_sellable_world(lot_quantity=100)
        customer, _order = setup_delivered_customer(
            "CascadeCust", spec["id"], 5)
        ret = log_pool_return(customer["id"], 2, "SCRAP")
        grade_pool_return(ret["id"], "SCRAP")
        return customer, ret

    def test_credit_scrap_return_spawns_grinding_queued_cores(self):
        """PRD §3.7: "Crediting posts the ledger in one motion — the customer's
        `pool_credit_balance_cents` grows by `total_credit_cents` and
        `pool_units_outstanding` shrinks by `returned_count` — and injects the
        physical units back into the core pipeline: each returned unit assessed
        `SCRAP` spawns a new core unit with `grade` `SCRAP` and
        `processing_status` `GRINDING_QUEUED`, while units assessed `A` or `B`
        re-enter as core units with their grade set and `processing_status`
        `YARD`, eligible for the repair pipeline of §3.4."
        PRD §3.7: "Grading resolves the per-unit credit from the pool credit
        tier table — an exact enum lookup with no interpolation: seven hundred
        cents per `A` unit, three hundred fifty per `B` unit, zero for `SCRAP`
        — into `credit_per_unit_cents`, and computes `total_credit_cents` as
        `returned_count` times that per-unit figure."

        Design: Difficulty/transitive_cascade/pool_credit_to_grinding_cascade
        """
        customer, ret = self._setup_scrap_return_ready_to_credit()
        resp = api_client.credit_pool_return(ret["id"], SALES)
        credited = validate_success(resp)
        assert credited["status"] == "CREDITED"
        assert credited["total_credit_cents"] == 0, (
            f"SCRAP tier pays zero credit, got {credited['total_credit_cents']}"
        )
        cust = get_customer(customer["id"])
        assert cust["pool_units_outstanding"] == 3, (
            f"5 delivered - 2 returned = 3 outstanding, "
            f"got {cust['pool_units_outstanding']}"
        )
        cores, meta = _list_grinding_queued_scrap_cores()
        assert len(cores) == 2, (
            f"crediting 2 SCRAP units must spawn 2 GRINDING_QUEUED cores, "
            f"got {len(cores)}"
        )
        for core in cores:
            assert core["grade"] == "SCRAP"
            assert core["processing_status"] == "GRINDING_QUEUED"

    def test_spawned_scrap_cores_grind_to_terminal_ground(self):
        """PRD §3.7: "each returned unit assessed `SCRAP` spawns a new core
        unit with `grade` `SCRAP` and `processing_status` `GRINDING_QUEUED`".
        PRD §3.9: "Completion computes the `yield_ratio` as `output_fiber_cuyd`
        divided by `input_count`, rounded half-up to 4 decimal places, and
        moves every input core's `processing_status` to terminal `GROUND`,
        ending the material's journey through the yard."

        Design: Difficulty/transitive_cascade/pool_credit_to_grinding_cascade
        """
        customer, ret = self._setup_scrap_return_ready_to_credit()
        credit_resp = api_client.credit_pool_return(ret["id"], SALES)
        validate_success(credit_resp)
        cores, _meta = _list_grinding_queued_scrap_cores()
        assert len(cores) == 2
        gb = create_grinding_batch([c["id"] for c in cores])
        start_resp = api_client.start_grinding_batch(gb["id"], YARD)
        validate_success(start_resp)
        done = validate_success(api_client.complete_grinding_batch(
            gb["id"], {"output_fiber_cuyd": 12.5, "revenue_cents": 9000},
            YARD))
        # 12.5 cuyd over 2 spawned cores -> 6.25 at 4 decimal places
        assert done["yield_ratio"] == pytest.approx(6.25, abs=1e-9), (
            f"yield_ratio must be 6.25, got {done['yield_ratio']}"
        )
        for core in cores:
            after = get_core(core["id"])
            assert after["processing_status"] == "GROUND", (
                f"cascade link 3: core must reach terminal GROUND, "
                f"got {after['processing_status']}"
            )
