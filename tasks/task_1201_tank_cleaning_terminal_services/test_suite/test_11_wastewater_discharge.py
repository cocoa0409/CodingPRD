"""Wastewater lab limits, daily capacity, and the void compensating action
(PRD §3.9)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_wastewater_batch_payload, submit_lab_payload,
    new_ctx, create_job, add_wastewater_batch,
)

OPERATOR = TEST_USERS["operator_headers"]
OPERATOR2 = TEST_USERS["operator2_headers"]
EHS = TEST_USERS["ehs_headers"]
LAB = TEST_USERS["lab_headers"]


def _ctx_with_job(api):
    ctx = new_ctx()
    create_job(ctx, heel_volume_liters_sounding=2000,
               base_service_fee_cents=500000)
    return ctx


class TestAuthorizeCheckOrder:
    def test_limits_error_beats_capacity_error(self, api):
        """PRD §3.9: "Authorization is the regulated step, and a `TerminalOperator` runs three checks in order. Segregation of duties comes first: the authorizer's `X-User-ID` must differ from the batch's `lab_user_id`, failing which `ERR_SEGREGATION_OF_DUTIES`. The discharge envelope comes next: pH must lie within the closed band from 6.0 to 9.0 and TPH must be at most 15.0 milligrams per liter inclusive, failing which `ERR_DISCHARGE_LIMITS_EXCEEDED` (HTTP 422). Daily capacity comes last"

        Design: Difficulty/priority_pair_validation_conflict/authorize_limits_beat_capacity
        """
        ctx = _ctx_with_job(api)
        # Exactly at capacity: the inclusive boundary passes.
        batch1 = add_wastewater_batch(ctx, 100000, authorize=True)
        assert batch1["status"] == "AUTHORIZED"

        batch2 = add_wastewater_batch(ctx, 50000, ph=9.5)
        # Both rules fail (pH 9.5 > 9.0; 100000+50000 > 100000): the discharge
        # envelope runs before the daily-capacity check.
        res = api.authorize_batch(batch2["id"], OPERATOR)
        validate_error(res, ApiErrorId.ERR_DISCHARGE_LIMITS_EXCEEDED)
        after = validate_success(api.get_wastewater_batch(batch2["id"], OPERATOR), 200)
        assert after["status"] == "LAB_TESTED"

    def test_capacity_alone_violated_returns_capacity_error(self, api):
        """PRD §3.9: "Daily capacity comes last: the batch's volume, added to the volumes of every batch of the same terminal already `AUTHORIZED` or `DISCHARGED` under the same `discharge_day`, must not exceed the terminal's `wastewater_daily_capacity_liters` — landing exactly on capacity is permitted — failing which `ERR_DISCHARGE_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/authorize_limits_beat_capacity
        """
        ctx = _ctx_with_job(api)
        add_wastewater_batch(ctx, 100000, authorize=True)
        batch2 = add_wastewater_batch(ctx, 1, ph=7.0, tph_mg_l=1.0)
        res = api.authorize_batch(batch2["id"], OPERATOR)
        validate_error(res, ApiErrorId.ERR_DISCHARGE_CAPACITY_EXCEEDED)


class TestDailyAllocationInvariant:
    def test_void_authorization_releases_the_days_liters(self, api):
        """PRD §3.9: "Voiding an authorization is the compensating action: it returns `AUTHORIZED` to `COLLECTED`, clears `discharge_day`, and releases the day's allocated liters back into the terminal's capacity."
        PRD §3.9: "Authorization stamps `discharge_day` with the current UTC calendar date from the logical clock, formatted YYYY-MM-DD, which is the key of the daily capacity bucket, and moves `LAB_TESTED` to `AUTHORIZED`."

        Design: Difficulty/compensating_invariant/wastewater_daily_allocation_authorize_void_invariant
        """
        ctx = _ctx_with_job(api)
        batch1 = add_wastewater_batch(ctx, 60000, authorize=True)
        assert batch1["status"] == "AUTHORIZED"

        voided = validate_success(
            api.void_authorization(batch1["id"], OPERATOR), 200)
        assert voided["status"] == "COLLECTED"
        assert voided["discharge_day"] is None

        # The full 100000 L fits only because the void released the 60000 L.
        batch2 = add_wastewater_batch(ctx, 100000, ph=7.5, tph_mg_l=4.0,
                                      authorize=True, authorize_headers=OPERATOR2)
        assert batch2["status"] == "AUTHORIZED"
        assert batch2["discharge_day"] == "2026-05-01"

        batch3 = add_wastewater_batch(ctx, 1, ph=7.0, tph_mg_l=1.0)
        res = api.authorize_batch(batch3["id"], OPERATOR)
        validate_error(res, ApiErrorId.ERR_DISCHARGE_CAPACITY_EXCEEDED)

    def test_discharged_batches_still_consume_capacity(self, api):
        """PRD §3.9: "the batch's volume, added to the volumes of every batch of the same terminal already `AUTHORIZED` or `DISCHARGED` under the same `discharge_day`, must not exceed the terminal's `wastewater_daily_capacity_liters`"
        PRD §3.9: "Discharge moves `AUTHORIZED` to `DISCHARGED`, the terminal state."

        Design: Difficulty/compensating_invariant/wastewater_daily_allocation_authorize_void_invariant
        """
        ctx = _ctx_with_job(api)
        batch1 = add_wastewater_batch(ctx, 60000, authorize=True)
        discharged = validate_success(api.discharge_batch(batch1["id"], OPERATOR), 200)
        assert discharged["status"] == "DISCHARGED"

        batch2 = add_wastewater_batch(ctx, 50000, ph=7.0, tph_mg_l=3.0)
        # 60000 (DISCHARGED) + 50000 > 100000: discharge does not free capacity.
        res = api.authorize_batch(batch2["id"], OPERATOR)
        validate_error(res, ApiErrorId.ERR_DISCHARGE_CAPACITY_EXCEEDED)


class TestBatchRejectCycle:
    def test_reject_return_to_storage_and_retest(self, api):
        """PRD §3.9: "An `EHSOfficer` may instead reject a `LAB_TESTED` batch outright, moving it to `REJECTED`, and returning a rejected batch to storage moves `REJECTED` back to `COLLECTED` for another attempt."

        Design: Corner/state_machines/batch_reject_return_to_storage_cycle
        """
        ctx = _ctx_with_job(api)
        batch = add_wastewater_batch(ctx, 5000, ph=8.0, tph_mg_l=3.0)
        assert batch["status"] == "LAB_TESTED"

        rejected = validate_success(api.reject_batch(batch["id"], EHS), 200)
        assert rejected["status"] == "REJECTED"
        stored = validate_success(
            api.return_batch_to_storage(batch["id"], OPERATOR), 200)
        assert stored["status"] == "COLLECTED"
        retested = validate_success(api.submit_lab_results(
            batch["id"], submit_lab_payload(ph=7.2, tph_mg_l=2.0), LAB), 200)
        assert retested["status"] == "LAB_TESTED"
