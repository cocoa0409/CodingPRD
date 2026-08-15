"""Finished-lot traceability, chill compliance, fresh-vs-frozen routing,
ship/recall lifecycle, and the certification-driven routing-flip cascade."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_utility_reading_payload, create_chill_chain_log_payload,
    create_condemnation_record_payload,
    make_line, make_order, make_batch, complete_batch, first_finished_lot,
    setup_chilled_lot, setup_settled_lot, setup_production_line_for_deboning,
    setup_finished_lot_open, setup_trace_locked_lot, setup_shipped_lot,
    set_clock,
    make_qa_technician_headers, make_usda_inspector_headers,
    TEST_USERS,
)

PM = TEST_USERS["plant_manager_headers"]
SUP = TEST_USERS["shift_supervisor_headers"]
OP = TEST_USERS["line_operator_headers"]
QA = TEST_USERS["qa_technician_headers"]


class TestTraceLockGates:

    def test_trace_lock_requires_certified_condemnations(self, api):
        """PRD §3.7: "First, every condemnation record on the source flock
        lot's runs must be `CERTIFIED`, else
        `ERR_TRACE_LOCK_BLOCKED_UNCERTIFIED`."

        Design: Difficulty/cross_entity_state_dependency/trace_lock_requires_certified_condemnations
        """
        env = setup_production_line_for_deboning(condemnation=100,
                                                 condemn_user_id="qa-1")
        # Record stays DRAFT; batch completes; finished lot OPEN
        env["batch"] = complete_batch(env["batch"]["id"])
        fl = first_finished_lot()
        resp = api.trace_lock_finished_lot(fl["id"], {}, QA)
        validate_error(resp, ApiErrorId.ERR_TRACE_LOCK_BLOCKED_UNCERTIFIED)
        after = get_success_data(api.get_finished_lot(fl["id"], QA))
        assert after["status"] == "OPEN"
        assert after["routing_status"] == "UNROUTED"

    def test_fresh_order_blocked_by_chiller_breach(self, api):
        """PRD §3.7: "Second, when the order's `temperature_requirement` is
        `FRESH`, the shift's `chiller_limit_breached` flag must be false — this
        regulatory safety check runs before any chill-window analysis and
        rejects with `ERR_CHILLER_LIMIT_FRESH_BLOCKED`."
        PRD §3.5: "Independently, `chiller_limit_breached` is true when
        `chiller_water_gallons` multiplied by 1000 and divided by
        `birds_processed` is strictly greater than the 800.0 chiller limit; it
        does not suspend the shift but blocks fresh routing at trace-lock."

        Design: Corner/calculations/fresh_order_blocked_by_chiller_breach
        """
        env = setup_trace_locked_env_fresh(api, chiller_breach=True, chill_temp_c=3.5)
        resp = api.trace_lock_finished_lot(env["finished_lot"]["id"], {}, QA)
        validate_error(resp, ApiErrorId.ERR_CHILLER_LIMIT_FRESH_BLOCKED)

    def test_fresh_order_chill_not_compliant(self, api):
        """PRD §3.7: "Third, again for `FRESH` orders, chill compliance must
        hold, else `ERR_CHILL_NOT_COMPLIANT`."
        PRD §3.7: "The lot is chill-compliant when some chill-chain log of this
        finished lot records a `temperature_c` no greater than 4.0 degrees at a
        `recorded_at` no later than eight hours after that reference instant,
        and the current logical time is no earlier than two hours after that
        reference instant".

        Design: Corner/calculations/fresh_order_chill_not_compliant
        """
        env = setup_trace_locked_env_fresh(api, chiller_breach=False, chill_temp_c=4.5)
        resp = api.trace_lock_finished_lot(env["finished_lot"]["id"], {}, QA)
        validate_error(resp, ApiErrorId.ERR_CHILL_NOT_COMPLIANT)

    def test_flexible_order_warm_chill_routes_frozen_not_error(self, api):
        """PRD §3.7: "For `FLEXIBLE`: if the lot is not chill-compliant, or the
        chiller limit is breached, it routes `FROZEN`; otherwise, if the flock
        lot's `certified_yield_pct` is at least the fresh-yield threshold of
        72.0 percent, it routes `FRESH` — a yield exactly at the threshold
        routes fresh — and otherwise it routes `FROZEN`."

        Design: Corner/calculations/flexible_order_warm_chill_routes_frozen_not_error
        """
        env = setup_finished_lot_open(temperature_requirement="FLEXIBLE",
                                      output_weight_lb=500.0, input_weight_lb=500.0,
                                      order_pounds=400.0, settle_lot=True)
        # 4.5C > 4.0C target: not chill-compliant
        get_success_data(api.create_chill_chain_log(
            create_chill_chain_log_payload(env["finished_lot"]["id"],
                                           temperature_c=4.5), QA))
        locked = validate_success(api.trace_lock_finished_lot(
            env["finished_lot"]["id"], {}, QA))
        assert locked["status"] == "TRACE_LOCKED"
        assert locked["routing_status"] == "FROZEN"

    def test_certified_yield_exactly_72_routes_fresh(self, api):
        """PRD §3.7: "otherwise, if the flock lot's `certified_yield_pct` is at
        least the fresh-yield threshold of 72.0 percent, it routes `FRESH` — a
        yield exactly at the threshold routes fresh — and otherwise it routes
        `FROZEN`."
        PRD §3.8: "The certified yield is the live-basis counterpart of the
        provisional figure of §3.4, computed over the same recorded data but
        through a different lens: from the lot's `carcass_weight_total_lb`,
        subtract the certified condemnation count — the sum of `effective_count`
        over records in `CERTIFIED` — multiplied by the average carcass weight,
        where the average carcass weight is the `carcass_weight_total_lb`
        divided by the `birds_hung_total` (the variant is undefined while
        `birds_hung_total` is zero); divide the result by `total_live_weight_lb`;
        multiply by 100; and round half-up to two decimal places."

        Design: Difficulty/boundary_precision_check/certified_yield_exactly_72_routes_fresh
        """
        env = setup_finished_lot_open(temperature_requirement="FLEXIBLE",
                                      output_weight_lb=500.0, input_weight_lb=500.0,
                                      order_pounds=400.0, settle_lot=True)
        # Zero condemnations: certified yield == 36000/50000*100 == 72.0 exactly
        assert env["lot"]["certified_yield_pct"] == pytest.approx(72.0)
        get_success_data(api.create_chill_chain_log(
            create_chill_chain_log_payload(env["finished_lot"]["id"],
                                           temperature_c=3.5), QA))
        locked = validate_success(api.trace_lock_finished_lot(
            env["finished_lot"]["id"], {}, QA))
        assert locked["routing_status"] == "FRESH"


def setup_trace_locked_env_fresh(api, chiller_breach, chill_temp_c):
    """Finished lot OPEN on a settled lot against a FRESH order, with one chill
    log at the given temperature; optionally breaches the chiller water limit
    (9000 gal over 9950 birds == 904.52 > 800.0) before trace-lock."""
    env = setup_finished_lot_open(temperature_requirement="FRESH",
                                  output_weight_lb=500.0, input_weight_lb=500.0,
                                  order_pounds=400.0, settle_lot=True,
                                  customer_name="CustF", product_code="BREAST_FILLET")
    if chiller_breach:
        get_success_data(api.create_utility_reading(
            create_utility_reading_payload(env["shift"]["id"],
                                           meter_type="CHILLER_WATER",
                                           gallons=9000.0), QA))
    get_success_data(api.create_chill_chain_log(
        create_chill_chain_log_payload(env["finished_lot"]["id"],
                                       temperature_c=chill_temp_c), QA))
    return env


class TestRoutingFlipCascade:

    def test_condemnation_recertify_yield_routing_flip_cascade(self, api):
        """PRD §3.4: "Third, if the lot is `SETTLED` or `REOPENED`, its
        `certified_yield_pct` is recomputed. Fourth, when that recomputation
        lowers the certified yield, finished lots of this flock lot in
        `TRACE_LOCKED` with `routing_status` `FRESH` whose order is `FLEXIBLE`
        flip from `FRESH` to `FROZEN` if the new certified yield has fallen
        below the fresh-yield threshold of §3.7."
        PRD §3.7: "The flip never runs `FROZEN` to `FRESH`, and it never
        touches lots already `SHIPPED` or `RECALLED`."

        Design: Difficulty/transitive_cascade/condemnation_recertify_yield_routing_flip_cascade
        """
        env = setup_trace_locked_lot(temperature_requirement="FLEXIBLE",
                                     chill_temp_c=3.5, lot_code="FL-200")
        fl = env["finished_lot"]
        assert env["lot"]["certified_yield_pct"] == pytest.approx(72.0)
        assert fl["routing_status"] == "FRESH"

        # Reopen the lot for regrade, record a new condemnation, certify it.
        get_success_data(api.advance_flock_lot(
            env["lot"]["id"], {"to_status": "REOPENED"},
            make_usda_inspector_headers("usda-1")))
        record = get_success_data(api.create_condemnation_record(
            create_condemnation_record_payload(env["run"]["id"],
                                               condemnation_code="BRUISING",
                                               carcass_count=100),
            make_qa_technician_headers("qa-1")))
        get_success_data(api.advance_condemnation_record(
            record["id"], {"to_status": "CERTIFIED"},
            make_usda_inspector_headers("usda-1")))

        lot = get_success_data(api.get_flock_lot(env["lot"]["id"], PM))
        assert lot["condemned_accounted"] == 100
        # (36000 - 100 * (36000/9950)) / 50000 * 100 == 71.28
        assert lot["certified_yield_pct"] == pytest.approx(71.28)

        flipped = get_success_data(api.get_finished_lot(fl["id"], QA))
        assert flipped["routing_status"] == "FROZEN"  # 71.28 < 72.0
        assert flipped["status"] == "TRACE_LOCKED"  # flip does not unlock


class TestShipAndRecall:

    def test_finished_lot_ship_twice_rejected(self, api):
        """PRD §3.7: "`SHIPPED` and `RECALLED` are terminal."
        PRD §2.6: "anything else unreachable from the current state is
        `ERR_INVALID_STATE_TRANSITION` (HTTP 409 throughout)."

        Design: Corner/state_machines/finished_lot_ship_twice_rejected
        """
        env = setup_shipped_lot(temperature_requirement="FROZEN")
        fid = env["finished_lot"]["id"]
        assert env["finished_lot"]["status"] == "SHIPPED"
        resp = api.advance_finished_lot(fid, {"to_status": "SHIPPED"}, SUP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_success_data(api.get_finished_lot(fid, QA))
        assert after["status"] == "SHIPPED"

    def test_finished_lot_recall_after_ship(self, api):
        """PRD §3.7: "Recall — to `RECALLED` from either `TRACE_LOCKED` or
        `SHIPPED` — is available to a `QATechnician` or `USDAInspector` and
        requires a `reason` (absent, `ERR_INVALID_REQUEST`)."

        Design: Corner/state_machines/finished_lot_recall_after_ship
        """
        env = setup_shipped_lot(temperature_requirement="FROZEN")
        recalled = validate_success(api.advance_finished_lot(
            env["finished_lot"]["id"],
            {"to_status": "RECALLED", "reason": "salmonella hold on lot"}, QA))
        assert recalled["status"] == "RECALLED"


class TestImmediateConsistency:

    def test_immediate_consistency_mutation_visible_in_response(self, api):
        """PRD §2.10: "The plant's consistency model is immediate: every
        mutation, together with all cascades it triggers, commits atomically
        within the request."
        PRD §3.4: "Completion stamps `completed_at`, then rolls up: the lot's
        `birds_hung_total` (the sum of `birds_hung` over the lot's runs in
        `COMPLETED` or `RECONCILED`) and `carcass_weight_total_lb` (the
        corresponding sum of `carcass_weight_lb`) are updated, as are the
        shift's `birds_processed` and `chilled_weight_lb` over the same
        population of runs".

        Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_response
        """
        from test_helpers import setup_running_shift_with_run, complete_run
        env = setup_running_shift_with_run()
        completed = validate_success(api.advance_line_run(
            env["run"]["id"], {"to_status": "COMPLETED", "birds_hung": 9950,
                               "carcass_weight_lb": 36000.0}, OP))
        # The mutation response itself carries the stored values
        assert completed["status"] in ("COMPLETED", "RECONCILED")
        assert completed["birds_hung"] == 9950
        # The cascade into lot aggregates is visible on the immediately-following GET
        lot = get_success_data(api.get_flock_lot(env["lot"]["id"], PM))
        assert lot["birds_hung_total"] == 9950
