"""Payout batch lifecycle, broker composite scorecard variants, and the
volume-forecast readout."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_batch,
    assert_volume_forecast,
    broker_decline,
    create_batch,
    create_client,
    create_volume_forecast_payload,
    disburse_batch,
    dispatch_to_broker,
    drive_order_to_completed,
    drive_order_to_report_submitted,
    get_broker,
    new_order,
    open_qc,
    record_verdict,
    set_clock,
    setup_market,
    submit_order,
    validate_error,
    validate_success,
)

BILLING = TEST_USERS["billing_clerk_headers"]
OPS = TEST_USERS["operations_manager_headers"]


class TestPayoutBatchLifecycle:
    def test_payout_batch_disbursed_is_terminal(self, api):
        """PRD §3.8: "on success sets each contributing order's `payment_status`
        to `PAID`, moving the batch to the terminal `DISBURSED`."
        PRD §2.9: "5. State legality: the target resource is in a state from
        which this transition is permitted (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/payout_batch_disbursed_is_terminal
        """
        env = setup_market("VA", client_code="CT2", broker_code="BT2",
                           client_overrides={"sla_hours_standard": 48,
                                             "sla_hours_rush": 24})
        drive_order_to_completed(env)
        batch = create_batch(env["broker"]["id"])
        assert batch["order_count"] == 1

        approved = approve_batch(batch)
        assert approved["status"] == "APPROVED"
        disbursed = disburse_batch(approved)
        assert disbursed["status"] == "DISBURSED"

        payload = {"expected_batch_version": disbursed["version"]}
        resp = api.approve_payout_batch(batch["id"], payload, BILLING)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        unchanged = validate_success(api.get_payout_batch(batch["id"], BILLING))
        assert unchanged["status"] == "DISBURSED"

    def test_empty_payout_batch_approve_rejected(self, api):
        """PRD §3.8: "Approval requires the OCC field `expected_batch_version`
        and at least one contributing order, else `ERR_EMPTY_BATCH`"

        Design: Corner/validations/empty_payout_batch_approve_rejected
        """
        env = setup_market("VT", client_code="CEB", broker_code="BEB")
        batch = create_batch(env["broker"]["id"])
        assert batch["order_count"] == 0

        payload = {"expected_batch_version": batch["version"]}
        resp = api.approve_payout_batch(batch["id"], payload, BILLING)
        validate_error(resp, ApiErrorId.ERR_EMPTY_BATCH)

    def test_occ_stale_version_on_payout_approve(self, api):
        """PRD §2.6: "Second, approving a payout batch requires the request body
        to carry `expected_batch_version`, set to the value of the batch's
        `version` the clerk last observed."
        PRD §2.9: "5. State legality: the target resource is in a state from
        which this transition is permitted (`ERR_INVALID_STATE`)."
        (A second approval after the first committed leaves the batch APPROVED,
        so the state-legality check — evaluated before the version check —
        discharges the repeated call.)

        Design: Corner/cross_cutting_layers/occ_stale_version_on_payout_approve
        """
        env = setup_market("SD", client_code="COC2", broker_code="BOC2",
                           client_overrides={"sla_hours_standard": 48,
                                             "sla_hours_rush": 24})
        drive_order_to_completed(env)
        batch = create_batch(env["broker"]["id"])
        stale_version = batch["version"]

        approved = approve_batch(batch)
        assert approved["status"] == "APPROVED"
        assert approved["version"] != stale_version

        payload = {"expected_batch_version": stale_version}
        resp = api.approve_payout_batch(batch["id"], payload, BILLING)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        unchanged = validate_success(api.get_payout_batch(batch["id"], BILLING))
        assert unchanged["status"] == "APPROVED"


class TestCompositeScoreVariants:
    def test_global_composite_pools_clients_with_order_count_weights(self, api):
        """PRD §3.3: "for the global view used in suspension decisions,
        components are pooled across all clients and the weights are the
        order-count-weighted averages of each contributing client's
        `scorecard_weight_turnaround`, `scorecard_weight_quality`, and
        `scorecard_weight_revision`"
        (Client A weights 0.8/0.1/0.1 with one on-time APPROVE; client B weights
        0.2/0.6/0.2 with one REJECT. Pooled: turnaround 1.0, quality 0.5,
        revision 1.0; averaged weights 0.5/0.35/0.15 ->
        100 * (0.5 + 0.175 + 0.15) = 82.50.)

        Design: Difficulty/dual_variant_calc/composite_score_client_weighted_vs_global
        """
        env = setup_market(
            "CA", client_code="CLA", broker_code="BRK1", license_kind="APPRAISAL",
            client_overrides={"scorecard_weight_turnaround": 0.8,
                              "scorecard_weight_quality": 0.1,
                              "scorecard_weight_revision": 0.1})
        client_b = create_client(
            "CLB", display_name="Client B",
            scorecard_weight_turnaround=0.2,
            scorecard_weight_quality=0.6,
            scorecard_weight_revision=0.2)

        # Order for client A: full path to an on-time COMPLETED with APPROVE.
        drive_order_to_completed(env, agreed_fee_cents=15000)

        # Order for client B: driven to a REJECT verdict (terminal REJECTED).
        order_b = drive_order_to_report_submitted(
            env, client=client_b, agreed_fee_cents=15000)
        qc_b = open_qc(order_b)
        record_verdict(order_b, qc_b, verdict="REJECT", defects_found=3,
                       notes="bad")

        # Read the score after the activity instants so every event falls
        # strictly inside the trailing-90-day window (the window excludes
        # "now").
        set_clock("2026-08-01T01:00:00Z")
        broker = get_broker(env["broker"]["id"])
        assert float(broker["composite_score"]) == 82.5, (
            f"Global pooled composite must be 82.50, got "
            f"{broker['composite_score']}")

    def test_global_composite_pools_quality_across_clients(self, api):
        """PRD §3.3: "The quality component is the mean verdict value across QC
        verdicts in the window, where an `APPROVE` verdict counts 1.0, a
        `REVISE` counts 0.5, and a `REJECT` counts 0.0."
        (Two clients sharing the default weights 0.5/0.3/0.2; one APPROVE and
        one REJECT: 100 * (0.5*1.0 + 0.3*0.5 + 0.2*1.0) = 85.00.)

        Design: Difficulty/dual_variant_calc/composite_score_client_weighted_vs_global
        """
        env = setup_market("CA", client_code="CLD2", broker_code="BRK2",
                           license_kind="APPRAISAL")
        client_e = create_client("CLE2", display_name="Client E2")

        drive_order_to_completed(env, agreed_fee_cents=15000)

        order_e = drive_order_to_report_submitted(
            env, client=client_e, agreed_fee_cents=15000)
        qc_e = open_qc(order_e)
        record_verdict(order_e, qc_e, verdict="REJECT", defects_found=3,
                       notes="bad")

        set_clock("2026-08-01T01:00:00Z")
        broker = get_broker(env["broker"]["id"])
        assert float(broker["composite_score"]) == 85.0, (
            f"Pooled quality mean across clients must yield 85.00, got "
            f"{broker['composite_score']}")


class TestCompositeScoreDeclinePenalty:
    def test_single_decline_subtracts_one_point(self, api):
        """PRD §3.3: "The weighted sum is multiplied by 100, each decline in the
        window then subtracts 1.0 point after weighting, and the result is
        rounded half-up to two decimal places and clamped to the inclusive range
        0 to 100."
        (One decline + one on-time APPROVE completion, default weights:
        100 * 1.0 - 1.0 = 99.00.)

        Design: Difficulty/combinatorial_formula/composite_score_multi_input_weighted_mode_a
        """
        env = setup_market("WA", client_code="CLC", broker_code="BRKC")
        declined = new_order(env, agreed_fee_cents=15000)
        declined = submit_order(env, declined)
        declined = dispatch_to_broker(env, declined)
        broker_decline(env, declined)

        drive_order_to_completed(env, agreed_fee_cents=15000)

        set_clock("2026-08-01T01:00:00Z")
        broker = get_broker(env["broker"]["id"])
        assert float(broker["composite_score"]) == 99.0, (
            f"One decline must subtract 1.0 point after weighting, got "
            f"{broker['composite_score']}")

    def test_two_declines_subtract_two_points(self, api):
        """PRD §3.3: "each decline in the window then subtracts 1.0 point after
        weighting"
        (Two declines + one on-time APPROVE completion, default weights:
        100 * 1.0 - 2.0 = 98.00.)

        Design: Difficulty/combinatorial_formula/composite_score_multi_input_weighted_mode_a
        """
        env = setup_market("WA", client_code="CLC", broker_code="BRKC")
        for _ in range(2):
            declined = new_order(env, agreed_fee_cents=15000)
            declined = submit_order(env, declined)
            declined = dispatch_to_broker(env, declined)
            broker_decline(env, declined)

        drive_order_to_completed(env, agreed_fee_cents=15000)

        set_clock("2026-08-01T01:00:00Z")
        broker = get_broker(env["broker"]["id"])
        assert float(broker["composite_score"]) == 98.0, (
            f"Two declines must subtract 2.0 points after weighting, got "
            f"{broker['composite_score']}")


class TestVolumeForecast:
    def test_volume_forecast_weighted_moving_average(self, api):
        """PRD §3.8: "letting the most recent completed month before
        `forecast_month` contribute count c1, the month before that c2, and the
        month before that c3, the predicted order count is three times c1 plus
        two times c2 plus one times c3, all divided by 6, rounded half-up to a
        whole count."
        PRD §3.8: "like other analytical records it carries only `id` and
        `created_at`."
        (With no completed orders in the trailing three months, c1=c2=c3=0 and
        the prediction is 0.)

        Design: Corner/calculations/volume_forecast_weighted_moving_average
        """
        setup_market("NM", client_code="CNM", broker_code="BNM")
        payload = create_volume_forecast_payload(
            state_code="NM", forecast_month="2026-08")
        forecast = validate_success(api.create_volume_forecast(payload, OPS), 201)
        assert_volume_forecast(forecast)
        assert forecast["predicted_order_count"] == 0
        assert forecast["state_code"] == "NM"
        assert forecast["forecast_month"] == "2026-08"
