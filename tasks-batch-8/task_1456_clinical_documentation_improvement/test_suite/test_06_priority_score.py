"""Case priority score: dual variants, acuity/LOS branches, boundary precision."""
import pytest

from test_helpers import (
    advance_clock,
    create_and_activate_review,
    create_case,
    create_policy,
    create_program,
    create_provider,
    create_query,
    get_case,
    send_query,
    setup_agreed_case,
    setup_sent_query,
)


class TestProvisionalVsResidualVariant:
    def test_open_sent_query_credits_proposed_weight(self, api):
        """PRD §3.2: "When a case in `OPEN` or `UNDER_REVIEW` has at least one
        query in `DRAFT`, `SENT`, or `ESCALATED` status, the provisional variant
        applies: the base opportunity is the larger of `working_drg_weight` and
        the largest `proposed_drg_weight` across those open queries, minus
        `initial_drg_weight`"
        PRD §3.2: "1.10 when `working_soi` is 2 and `working_rom` is at most 2"
        PRD §3.2: "1.30 when the program's `current_period_index` is strictly
        greater than the case's `discharge_period`"

        Design: Difficulty/dual_variant_calc/priority_score_provisional_vs_residual_on_open_query
        """
        from test_helpers import respond_to_query
        program = create_program()
        policy = create_policy(
            program["id"], response_due_periods=3, escalation_stage_periods=2,
            max_escalation_stage=2,
        )
        provider = create_provider(program["id"])
        advance_clock(program["id"], 5)
        case = create_case(
            program["id"], provider["id"],
            admission_period=0, discharge_period=4,
            initial_drg_code="DRG-A", initial_drg_weight=1.0,
        )
        review = create_and_activate_review(case["id"])
        # First query AGREED with same weight but soi=2/rom=2 -> working_soi/rom = 2
        q1 = create_query(
            review["id"], provider["id"], policy["id"],
            query_text="Please clarify the documented acuity level.",
            clinical_indicators=["WBC-14"],
            proposed_drg_code="DRG-A", proposed_drg_weight=1.0,
            proposed_soi=2, proposed_rom=2,
        )
        q1 = send_query(q1["id"], q1["version"])
        respond_to_query(q1["id"], provider["id"], response_type="AGREE")
        # Second query still open (SENT) proposing a higher weight.
        q2 = create_query(
            review["id"], provider["id"], policy["id"],
            query_text="Please clarify the documented acuity level.",
            clinical_indicators=["WBC-14", "fever"],
            proposed_drg_code="DRG-B", proposed_drg_weight=1.5,
            proposed_soi=3, proposed_rom=3,
        )
        send_query(q2["id"], q2["version"])
        case_after = get_case(case["id"])
        assert case_after["working_soi"] == 2
        assert case_after["working_rom"] == 2
        # provisional: base = max(working 1.0, max proposed 1.5) - initial 1.0 = 0.5
        # acuity = 1.10 (working soi 2, rom <= 2); los = 1.30 (period 5 > discharge 4)
        # score = 0.5 * 1.10 * 1.30 * 100 = 71.5
        assert case_after["priority_score"] == pytest.approx(71.5, abs=1e-4)

    def test_no_open_queries_uses_residual_variant(self, api):
        """PRD §3.2: "When a case has no open queries, or is `RECONCILED`, the
        residual variant applies: the base opportunity is simply
        `working_drg_weight` minus `initial_drg_weight` — only realized deltas
        count."

        Design: Difficulty/dual_variant_calc/priority_score_provisional_vs_residual_on_open_query
        """
        program = create_program()
        provider = create_provider(program["id"])
        advance_clock(program["id"], 5)
        case = create_case(
            program["id"], provider["id"],
            admission_period=0, discharge_period=4,
            initial_drg_code="DRG-A", initial_drg_weight=1.0,
        )
        case_after = get_case(case["id"])
        # residual with no realized delta: base = max(0, 1.0 - 1.0) = 0
        assert case_after["priority_score"] == pytest.approx(0.0, abs=1e-4)


class TestAcuityAndLosBranches:
    def test_soi3_rom2_post_discharge_score(self, api):
        """PRD §3.2: "1.25 when `working_soi` is 3 or `working_rom` is 3"
        PRD §3.2: "1.30 when the program's `current_period_index` is strictly
        greater than the case's `discharge_period`"
        PRD §3.2: "The score is the product of three tiers, multiplied by 100 and
        rounded half-up to 4 decimal places."

        Design: Difficulty/combinatorial_formula/priority_score_multibranch_acuity_and_los
        """
        scenario = setup_agreed_case(
            proposed_drg_weight=1.8, proposed_soi=3, proposed_rom=2,
            proposed_drg_code="DRG-B", initial_drg_weight=1.2, initial_drg_code="DRG-A",
            discharge_period=4, response_due_periods=1, escalation_stage_periods=1,
            max_escalation_stage=1,
        )
        advance_clock(scenario["program"]["id"], 7)
        case = get_case(scenario["case"]["id"])
        # residual (query RESPONDED): base = 1.8 - 1.2 = 0.6
        # acuity = 1.25 (soi 3); los = 1.30 (period 7 > discharge 4)
        # score = 0.6 * 1.25 * 1.30 * 100 = 97.5
        assert case["priority_score"] == pytest.approx(97.5, abs=1e-4)

    def test_soi1_rom1_pre_discharge_score(self, api):
        """PRD §3.2: "it is 1.00 when both `working_soi` and `working_rom` are 1"
        PRD §3.2: "1.00 when it is still below it."

        Design: Difficulty/combinatorial_formula/priority_score_multibranch_acuity_and_los
        """
        scenario = setup_agreed_case(
            proposed_drg_weight=2.0, proposed_soi=1, proposed_rom=1,
            proposed_drg_code="DRG-B", initial_drg_weight=1.0, initial_drg_code="DRG-A",
            discharge_period=10, response_due_periods=1, escalation_stage_periods=1,
            max_escalation_stage=1,
        )
        case = get_case(scenario["case"]["id"])
        # residual: base = 2.0 - 1.0 = 1.0; acuity 1.00 (soi=rom=1);
        # los 1.00 (period 0 < discharge 10) -> 100.0
        assert case["priority_score"] == pytest.approx(100.0, abs=1e-4)


class TestLosBoundary:
    def test_los_at_discharge_period_is_1_15(self, api):
        """PRD §3.2: "1.15 when it equals `discharge_period`"

        Design: Difficulty/boundary_precision_check/los_factor_discharge_period_boundary
        """
        scenario = setup_agreed_case(
            proposed_drg_weight=2.0, proposed_soi=1, proposed_rom=1,
            proposed_drg_code="DRG-B", initial_drg_weight=1.0, initial_drg_code="DRG-A",
            discharge_period=4, response_due_periods=10, escalation_stage_periods=10,
            max_escalation_stage=1,
        )
        advance_clock(scenario["program"]["id"], 4)
        case = get_case(scenario["case"]["id"])
        # base 1.0 * acuity 1.00 * los 1.15 * 100
        assert case["priority_score"] == pytest.approx(115.0, abs=1e-4)

    def test_los_past_discharge_period_is_1_30(self, api):
        """PRD §3.2: "1.30 when the program's `current_period_index` is strictly
        greater than the case's `discharge_period`"

        Design: Difficulty/boundary_precision_check/los_factor_discharge_period_boundary
        """
        scenario = setup_agreed_case(
            proposed_drg_weight=2.0, proposed_soi=1, proposed_rom=1,
            proposed_drg_code="DRG-B", initial_drg_weight=1.0, initial_drg_code="DRG-A",
            discharge_period=4, response_due_periods=10, escalation_stage_periods=10,
            max_escalation_stage=1,
        )
        advance_clock(scenario["program"]["id"], 5)
        case = get_case(scenario["case"]["id"])
        # base 1.0 * acuity 1.00 * los 1.30 * 100
        assert case["priority_score"] == pytest.approx(130.0, abs=1e-4)
