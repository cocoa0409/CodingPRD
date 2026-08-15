"""Blending two dried lots to a contract moisture: Pearson-square quantities,
ceil rounding, segregation of duties, cross-lot compatibility, and execute-time
revalidation (PRD §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_blend_order,
    approve_blend_order,
    create_approved_blend_order,
    create_blend_order,
    create_customer,
    create_dried_lot,
    create_filed_claim,
    get_lot,
    make_manager_headers,
    setup_base,
    validate_error,
    validate_success,
)


def _dried_pair(ctx, *, high=None, low=None):
    """Two DRIED lots on the base unit: high run 08:00-10:00, low run 11:00-13:00."""
    high = high or {}
    low = low or {}
    dried_h = create_dried_lot(
        ctx["cust"]["id"], ctx["unit"]["id"],
        run_start="2026-09-05T08:00:00Z", run_end="2026-09-05T10:00:00Z",
        meter_start=100.0, meter_end=160.0, **high)
    dried_l = create_dried_lot(
        ctx["cust2"]["id"] if "cust2" in ctx else ctx["cust"]["id"],
        ctx["unit"]["id"],
        run_start="2026-09-05T11:00:00Z", run_end="2026-09-05T13:00:00Z",
        meter_start=100.0, meter_end=160.0, **low)
    return dried_h, dried_l


# Canonical pair: high 7000 lbs @17.0, low 5000 lbs @13.0.
_HIGH = dict(gross_weight_lbs=41500, target_moisture_pct=17.0,
             foreign_material_pct=2.0, sample_moisture_pct=19.0,
             scale_out=7000, discharge=17.0)
_LOW = dict(gross_weight_lbs=39400, target_moisture_pct=13.0,
            foreign_material_pct=2.0, sample_moisture_pct=14.0,
            scale_out=5000, discharge=13.0)


class TestBlendExecution:
    def test_blend_execute_happy_mints_result_lot(self, api, manager_headers):
        """PRD §3.7: "A successful execution consumes both sources — each moves
        `DRIED` → `BLENDED_OUT`, terminal, version incrementing — and mints a
        result grain lot: the sources' commodity, customer, and owner; `status`
        `DRIED`; and weights and moisture from the blend arithmetic. The order's
        `result_weight_lbs` is the high source's `final_dry_weight_lbs` plus
        `required_low_lot_lbs`, and the result lot takes that figure as both its
        `wet_net_weight_lbs` and its `final_dry_weight_lbs`. The order's
        `result_moisture_pct` is the weight-mean moisture — the high source's
        final weight times its moisture plus the required low pounds times the
        low source's moisture, all divided by the result weight, rounded half up
        to two decimal places — and the result lot adopts it as both
        `intake_moisture_pct` and `current_moisture_pct`."

        Design: Corner/state_machines/blend_execute_happy_mints_result_lot
        """
        ctx = setup_base()
        dried_h, dried_l = _dried_pair(ctx, high=_HIGH, low=_LOW)
        order = create_blend_order(dried_h["lot"]["id"], dried_l["lot"]["id"], 15.5)
        # ceil(7000 * 1.5 / 2.5) = 4200 exactly
        assert order["required_low_lot_lbs"] == 4200
        order = validate_success(
            api.approve_blend_order(order["id"], make_manager_headers("mgr-2")), 200)
        executed = validate_success(
            api.execute_blend_order(order["id"], manager_headers), 200)
        assert_blend_order(executed)
        assert executed["status"] == "EXECUTED"
        assert executed["result_weight_lbs"] == 11200
        assert executed["result_moisture_pct"] == pytest.approx(15.5)

        result_lot = validate_success(
            api.get_grain_lot(executed["result_lot_id"], manager_headers), 200)
        assert result_lot["status"] == "DRIED"
        assert result_lot["wet_net_weight_lbs"] == 11200
        assert result_lot["current_moisture_pct"] == pytest.approx(15.5)
        assert get_lot(dried_h["lot"]["id"])["status"] == "BLENDED_OUT"
        assert get_lot(dried_l["lot"]["id"])["status"] == "BLENDED_OUT"

    def test_blend_ceil_rounds_low_side_up(self, api, manager_headers):
        """PRD §3.7: "The order's `required_low_lot_lbs` is that quotient rounded
        up to whole pounds — rounding up, never nearest, so the finished blend
        cannot land wetter than the contract target."

        Design: Corner/calculations/blend_ceil_rounds_low_side_up
        """
        ctx = setup_base()
        high = dict(gross_weight_lbs=39000, target_moisture_pct=17.3,
                    sample_moisture_pct=19.3, scale_out=5000, discharge=17.3)
        low = dict(gross_weight_lbs=40000, target_moisture_pct=12.9,
                   sample_moisture_pct=14.9, scale_out=5600, discharge=12.9)
        dried_h, dried_l = _dried_pair(ctx, high=high, low=low)
        order = create_blend_order(dried_h["lot"]["id"], dried_l["lot"]["id"], 15.0)
        # ceil(5000 * 2.3 / 2.1 = 5476.19...) = 5477 — rounds UP
        assert order["required_low_lot_lbs"] == 5477
        order = validate_success(
            api.approve_blend_order(order["id"], make_manager_headers("mgr-2")), 200)
        executed = validate_success(
            api.execute_blend_order(order["id"], manager_headers), 200)
        assert executed["result_weight_lbs"] == 10477
        # (5000*17.3 + 5477*12.9)/10477 = 14.9998... -> 15.0, never above target
        assert executed["result_moisture_pct"] == pytest.approx(15.0)


class TestBlendCompatibility:
    def test_blend_commodity_mismatch_rejected(self, api, manager_headers):
        """PRD §3.7: "Both sources must stand `DRIED`, share one commodity
        (`ERR_BLEND_COMMODITY_MISMATCH`, HTTP 422), and share one current owner
        (`ERR_BLEND_OWNERSHIP_MISMATCH`, HTTP 422)."

        Design: Corner/validations/blend_commodity_mismatch_rejected
        """
        ctx = setup_base()
        high = dict(_HIGH, commodity="CORN")
        low = dict(_LOW, commodity="SOYBEAN")
        dried_h, dried_l = _dried_pair(ctx, high=high, low=low)
        res = api.create_blend_order(
            {"high_moisture_lot_id": dried_h["lot"]["id"],
             "low_moisture_lot_id": dried_l["lot"]["id"],
             "target_moisture_pct": 15.5},
            make_manager_headers("mgr-1"),
        )
        validate_error(res, ApiErrorId.ERR_BLEND_COMMODITY_MISMATCH,
                       expected_status=422)

    def test_blend_ownership_mismatch_rejected(self, api, manager_headers):
        """PRD §3.7: "Both sources must stand `DRIED`, share one commodity
        (`ERR_BLEND_COMMODITY_MISMATCH`, HTTP 422), and share one current owner
        (`ERR_BLEND_OWNERSHIP_MISMATCH`, HTTP 422)."

        Design: Corner/validations/blend_ownership_mismatch_rejected
        """
        ctx = setup_base()
        ctx["cust2"] = create_customer(name="CB")
        dried_h, dried_l = _dried_pair(ctx, high=dict(_HIGH), low=dict(_LOW))
        res = api.create_blend_order(
            {"high_moisture_lot_id": dried_h["lot"]["id"],
             "low_moisture_lot_id": dried_l["lot"]["id"],
             "target_moisture_pct": 15.5},
            make_manager_headers("mgr-1"),
        )
        validate_error(res, ApiErrorId.ERR_BLEND_OWNERSHIP_MISMATCH,
                       expected_status=422)


class TestBlendSegregation:
    def test_blend_approver_conflict_rejected(self, api, manager_headers):
        """PRD §3.7: "Approval enforces the §2.8 segregation rule: a manager
        whose id differs from `created_by_user_id` moves the order `DRAFT` →
        `APPROVED`, recorded in `approved_by_user_id`; the creator approving
        their own order is `ERR_BLEND_APPROVER_CONFLICT` (HTTP 403)."

        Design: Corner/validations/blend_approver_conflict_rejected
        """
        ctx = setup_base()
        dried_h, dried_l = _dried_pair(ctx, high=dict(_HIGH), low=dict(_LOW))
        order = create_blend_order(dried_h["lot"]["id"], dried_l["lot"]["id"], 15.5,
                                   creator_id="mgr-1")
        res = api.approve_blend_order(order["id"], make_manager_headers("mgr-1"))
        validate_error(res, ApiErrorId.ERR_BLEND_APPROVER_CONFLICT,
                       expected_status=403)
        assert validate_success(
            api.get_blend_order(order["id"], manager_headers), 200)["status"] == "DRAFT"


class TestBlendExecuteRevalidation:
    def test_execute_blocked_when_source_on_damage_hold(self, api, manager_headers):
        """PRD §3.7: "Execution re-verifies everything against the live lots.
        The order must be `APPROVED`; both sources must still stand `DRIED`
        (otherwise `ERR_INVALID_STATE` — a source that has been loaded out,
        re-claimed, or stored into an active agreement cannot blend); and
        `required_low_lot_lbs` must not exceed the low source's available
        `final_dry_weight_lbs`, or `ERR_INSUFFICIENT_BLEND_GRAIN` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/blend_execute_requires_sources_dried
        """
        ctx = setup_base()
        dried_h, dried_l = _dried_pair(ctx, high=dict(_HIGH), low=dict(_LOW))
        order = create_approved_blend_order(
            dried_h["lot"]["id"], dried_l["lot"]["id"], 15.5)
        # Between approval and execution the high lot moves to DAMAGE_HOLD.
        claim = create_filed_claim(dried_h["lot"], dried_h["run"],
                                   claimed_amount_cents=5000)
        assert get_lot(dried_h["lot"]["id"])["status"] == "DAMAGE_HOLD"
        res = api.execute_blend_order(order["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_failed_execute_leaves_order_and_sources_untouched(self, api, manager_headers):
        """PRD §3.7: "The order must be `APPROVED`; both sources must still
        stand `DRIED` (otherwise `ERR_INVALID_STATE` — a source that has been
        loaded out, re-claimed, or stored into an active agreement cannot
        blend)"
        PRD §3.7: "At creation the order computes how much of the drier lot the
        blend requires, by the Pearson square."

        Design: Difficulty/cross_entity_state_dependency/blend_execute_requires_sources_dried
        """
        ctx = setup_base()
        dried_h, dried_l = _dried_pair(ctx, high=dict(_HIGH), low=dict(_LOW))
        order = create_blend_order(dried_h["lot"]["id"], dried_l["lot"]["id"], 15.5)
        assert order["required_low_lot_lbs"] == 4200  # 7000 * 1.5 / 2.5 exact
        approve_blend_order(order["id"], approver_id="mgr-2")
        create_filed_claim(dried_h["lot"], dried_h["run"], claimed_amount_cents=5000)
        validate_error(api.execute_blend_order(order["id"], manager_headers),
                       ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        # No partial consumption: order stays APPROVED, low source stays DRIED.
        assert validate_success(
            api.get_blend_order(order["id"], manager_headers), 200)["status"] == "APPROVED"
        assert get_lot(dried_l["lot"]["id"])["status"] == "DRIED"
