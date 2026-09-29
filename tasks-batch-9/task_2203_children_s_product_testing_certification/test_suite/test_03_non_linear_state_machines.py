"""A machine that re-enters a state, and a row that carries two independent axes."""

from test_helpers import ApiErrorId, fixtures as fx, validate_error
from test_helpers.test_users import MANAGER_HEADERS


LEAD_RULE = {
    "hazard_class": "LEAD_CONTENT",
    "severity_weight": 9,
    "limit_value": 100,
    "limit_unit": "PPM",
    "base_method_fee_cents": 18700,
}

FLAT_CATEGORY = {"durable_infant_product": False, "sampling_floor_units": 1}


def _stopped_case_env(api):
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    return fx.stopped_case_env(
        api,
        scope_variant="BATCH_SCOPED",
        rule_specs=[dict(LEAD_RULE)],
        category=dict(FLAT_CATEGORY),
        product={"projected_annual_units": 6000, "testing_budget_cents": 2000000},
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 4},
        failing_measured_value=250,
        failing_order_overrides={
            "window_start": "2026-08-02T00:00:00Z",
            "window_end": "2026-08-03T00:00:00Z",
        },
    )


ROUND_WINDOWS = [
    ("2026-08-04T00:00:00Z", "2026-08-05T00:00:00Z", 240),
    ("2026-08-06T00:00:00Z", "2026-08-07T00:00:00Z", 230),
    ("2026-08-08T00:00:00Z", "2026-08-09T00:00:00Z", 220),
]


class TestRetestCycle:
    """RETEST_ORDERED is left and re-entered, and the loop is bounded."""

    def test_case_reenters_retest_ordered_on_every_round_the_counter_allows(self, api):
        """PRD 3.9: "On the ordering path the case moves `STOP_DISTRIBUTION_ISSUED →
        RETEST_ORDERED` on the first round, or `RETEST_FAILED → RETEST_ORDERED` on
        every subsequent round."

        Design: Difficulty/non_linear_state_machine/non_linear_noncompliance_case_retest_cycle_reenters_retest_ordered_then_escalates_at_third_round
        """
        env = _stopped_case_env(api)
        case_id = env["case"]["id"]
        lab_id = env["laboratory"]["id"]

        for expected_count_before, (start, end, measured) in enumerate(ROUND_WINDOWS):
            before = fx.get_case(api, case_id)
            assert before["retest_round_count"] == expected_count_before
            ordered = fx.order_retest(
                api,
                case_id,
                env["plan"]["id"],
                lab_id,
                sample_count=1,
                window_start=start,
                window_end=end,
            )
            assert ordered["case_state"] == "RETEST_ORDERED"
            assert ordered["retest_round_count"] == expected_count_before + 1
            assert ordered["active_retest_order_id"] is not None

            retest_order_id = ordered["active_retest_order_id"]
            fx.start_order(api, retest_order_id, lab_id)
            fx.report(api, retest_order_id, lab_id, measured)
            after = fx.get_case(api, case_id)
            assert after["case_state"] == "RETEST_FAILED"
            assert after["active_retest_order_id"] is None

        final = fx.get_case(api, case_id)
        assert final["case_state"] == "RETEST_FAILED"
        assert final["retest_round_count"] == 3

    def test_fourth_retest_request_escalates_to_recall_without_creating_an_order(self, api):
        """PRD 3.9: "On the escalation path — `RETEST_FAILED → ESCALATED_RECALL`, taken
        by the same retest endpoint once the round threshold is reached — no test order
        is created at all."

        Design: Difficulty/non_linear_state_machine/non_linear_noncompliance_case_retest_cycle_reenters_retest_ordered_then_escalates_at_third_round
        """
        env = _stopped_case_env(api)
        case_id = env["case"]["id"]
        lab_id = env["laboratory"]["id"]

        for start, end, measured in ROUND_WINDOWS:
            ordered = fx.order_retest(
                api,
                case_id,
                env["plan"]["id"],
                lab_id,
                sample_count=1,
                window_start=start,
                window_end=end,
            )
            retest_order_id = ordered["active_retest_order_id"]
            fx.start_order(api, retest_order_id, lab_id)
            fx.report(api, retest_order_id, lab_id, measured)

        escalated = fx.order_retest(
            api,
            case_id,
            env["plan"]["id"],
            lab_id,
            sample_count=1,
            window_start="2026-08-11T00:00:00Z",
            window_end="2026-08-12T00:00:00Z",
        )
        assert escalated["case_state"] == "ESCALATED_RECALL"
        assert escalated["case_state"] != "RETEST_ORDERED"
        assert escalated["retest_round_count"] == 3
        assert escalated["scope_variant"] == "LOT_TRACEBACK"

        retests = fx.list_orders_for_product(api, env["product"]["id"], is_retest=True)
        assert len(retests) == 3

    def test_round_threshold_is_read_before_the_call_increments_the_counter(self, api):
        """PRD 3.9: "When `retest_round_count` is at or above the maximum of 3 retest
        rounds, the case escalates; otherwise it orders another round."

        Design: Difficulty/non_linear_state_machine/non_linear_noncompliance_case_retest_cycle_reenters_retest_ordered_then_escalates_at_third_round
        """
        env = _stopped_case_env(api)
        case_id = env["case"]["id"]
        lab_id = env["laboratory"]["id"]

        for index, (start, end, measured) in enumerate(ROUND_WINDOWS):
            ordered = fx.order_retest(
                api,
                case_id,
                env["plan"]["id"],
                lab_id,
                sample_count=1,
                window_start=start,
                window_end=end,
            )
            # A case at 2 orders one more retest and lands at 3.
            assert ordered["retest_round_count"] == index + 1
            assert ordered["case_state"] == "RETEST_ORDERED"
            fx.start_order(api, ordered["active_retest_order_id"], lab_id)
            fx.report(api, ordered["active_retest_order_id"], lab_id, measured)

        plan = fx.get_plan(api, env["plan"]["id"])
        assert plan["units_committed"] + plan["units_available"] == plan["units_authorized"]


def _evidence_complete_env(api):
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    return fx.evidence_complete_env(
        api,
        rule_specs=[dict(LEAD_RULE)],
        category=dict(FLAT_CATEGORY),
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 4},
        measured_value=40,
    )


class TestCertificateParallelAxes:
    """Issuance and accompaniment reach terminal values without dragging each other."""

    def test_voiding_a_draft_moves_only_the_issuance_axis(self, api):
        """PRD 3.7: "The two axes advance independently: no movement on one constrains
        the other except where a precondition explicitly says so, and there is exactly
        one such coupling, named below."

        Design: Difficulty/non_linear_state_machine/non_linear_certificate_parallel_dimensions_issuance_and_accompaniment_advance_independently
        """
        env = _evidence_complete_env(api)
        product = fx.get_product(api, env["product"]["id"])
        certificate_a = fx.draft_certificate(api, product["id"], product["version"])
        assert certificate_a["issuance_status"] == "DRAFT"
        assert certificate_a["accompaniment_status"] == "NOT_FURNISHED"

        voided = fx.void_certificate(api, certificate_a["id"])
        assert voided["issuance_status"] == "VOIDED"
        assert voided["accompaniment_status"] == "NOT_FURNISHED"
        assert fx.get_product(api, product["id"])["certification_state"] == "EVIDENCE_COMPLETE"

    def test_recalling_accompaniment_leaves_the_issuance_axis_at_issued(self, api):
        """PRD 3.7: "The same manager may later withdraw the certificate from
        shipments, moving it `FURNISHED → RECALLED_FROM_SHIPMENTS`, which blocks further
        batch releases against it; `issuance_status` is explicitly left unchanged by
        that move, so an `ISSUED` certificate stays `ISSUED`."

        Design: Difficulty/non_linear_state_machine/non_linear_certificate_parallel_dimensions_issuance_and_accompaniment_advance_independently
        """
        env = _evidence_complete_env(api)
        product = fx.get_product(api, env["product"]["id"])
        certificate_a = fx.draft_certificate(api, product["id"], product["version"])
        fx.void_certificate(api, certificate_a["id"])

        product = fx.get_product(api, env["product"]["id"])
        certificate_b = fx.draft_certificate(api, product["id"], product["version"])
        issued = fx.issue_certificate(api, certificate_b["id"])
        assert issued["issuance_status"] == "ISSUED"
        assert issued["accompaniment_status"] == "NOT_FURNISHED"
        assert issued["supersedes_certificate_id"] is None
        certified = fx.get_product(api, env["product"]["id"])
        assert certified["certification_state"] == "CERTIFIED"
        assert certified["compliance_posture"] == "CLEARED"

        furnished = fx.furnish_certificate(api, certificate_b["id"])
        assert furnished["accompaniment_status"] == "FURNISHED"
        assert furnished["issuance_status"] == "ISSUED"

        recalled = fx.recall_accompaniment(api, certificate_b["id"])
        assert recalled["accompaniment_status"] == "RECALLED_FROM_SHIPMENTS"
        assert recalled["issuance_status"] == "ISSUED"

        assert fx.get_certificate(api, certificate_a["id"])["accompaniment_status"] == (
            "NOT_FURNISHED"
        )

    def test_furnishing_a_voided_certificate_is_refused_by_the_single_cross_axis_coupling(
        self, api
    ):
        """PRD 3.7: "This is the single cross-axis coupling in the whole machine:
        furnishing requires the issuance axis to have reached `ISSUED`, and attempting
        it on a draft is refused with `ERR_CERTIFICATE_STATE_INVALID`."

        Design: Difficulty/non_linear_state_machine/non_linear_certificate_parallel_dimensions_issuance_and_accompaniment_advance_independently
        """
        env = _evidence_complete_env(api)
        product = fx.get_product(api, env["product"]["id"])
        certificate_a = fx.draft_certificate(api, product["id"], product["version"])
        fx.void_certificate(api, certificate_a["id"])

        validate_error(
            api.furnish_certificate(certificate_a["id"], headers=MANAGER_HEADERS),
            ApiErrorId.CERTIFICATE_STATE_INVALID.value,
            409,
        )
        assert fx.get_certificate(api, certificate_a["id"])["accompaniment_status"] == (
            "NOT_FURNISHED"
        )
