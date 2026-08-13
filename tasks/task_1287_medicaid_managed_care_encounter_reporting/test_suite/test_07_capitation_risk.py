"""Capitation statements (provisional vs final), pinned per-member rounding, and risk
score normalization."""
import pytest

from test_helpers import (
    ApiErrorId,
    acknowledge_batch,
    create_acknowledged_encounter,
    create_batch,
    create_encounter,
    create_encounter_line,
    create_member,
    create_program,
    create_provider,
    create_rate_schedule,
    create_cycle,
    create_statement,
    get_success_data,
    seal_batch,
    stage_encounter,
    transmit_batch,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client
from test_helpers.fixtures import FIN, OPS, STATE


def _acknowledge_with_diagnoses(program_id, cycle_id, provider_id, member, encounter_ref, diagnosis_codes):
    """Drive one encounter to ACKNOWLEDGED carrying the given diagnosis codes."""
    encounter = create_encounter(program_id, member["id"], provider_id, encounter_ref=encounter_ref,
                                 diagnosis_codes=diagnosis_codes)
    validated = get_success_data(api_client.validate_encounter(encounter["id"], OPS))
    assert validated["status"] == "VALIDATED", "Setup failed: encounter must validate cleanly"
    batch = create_batch(cycle_id)
    batch = stage_encounter(batch, encounter["id"])
    batch = seal_batch(batch)
    batch = transmit_batch(batch)
    acknowledge_batch(batch, [{"encounter_id": encounter["id"], "outcome": "ACCEPTED"}])
    return get_success_data(api_client.get_encounter(encounter["id"], OPS))


class TestProvisionalVsFinalDivergence:
    def _setup_risk_scored_cycle(self, program_name="P-CAP"):
        """3 TANF members at 50000 + 1 SSI member at 120000; raw scores 0.8/1.2/0.0/2.0
        (average 1.0, so normalized scores equal raw)."""
        program = create_program(name=program_name)
        create_rate_schedule(program["id"], aid_category="TANF", pmpm_cents=50000)
        create_rate_schedule(program["id"], aid_category="SSI", pmpm_cents=120000)
        cycle = create_cycle(program["id"])
        m1 = create_member(program["id"], aid_category="TANF")
        m2 = create_member(program["id"], aid_category="TANF")
        m3 = create_member(program["id"], aid_category="TANF")
        m4 = create_member(program["id"], aid_category="SSI")
        provider = create_provider(program["id"])
        _acknowledge_with_diagnoses(program["id"], cycle["id"], provider["id"], m1, "E1", ["E11"])
        _acknowledge_with_diagnoses(program["id"], cycle["id"], provider["id"], m2, "E2", ["I50"])
        _acknowledge_with_diagnoses(program["id"], cycle["id"], provider["id"], m4, "E3", ["E11", "I50"])
        # m3 has no encounter => raw 0
        snapshots = validate_success(api_client.compute_risk_scores(cycle["id"], FIN))
        assert len(snapshots) == 4
        statement = create_statement(cycle["id"])
        return {"program": program, "cycle": cycle, "statement": statement,
                "members": [m1, m2, m3, m4], "provider": provider}

    def test_capitation_provisional_vs_final_divergence(self):
        """PRD §3.9: "Issuance computes `member_months` as the count of members whose
        enrollment interval overlaps the cycle's half-open window by at least one day,
        and prices the `provisional_paid_cents` with risk pinned at 1.0 for every
        member"
        PRD §3.9: "The same member-months can therefore reconcile to a materially
        different total than the provisional issue — a provisional 270000 cents can
        settle to a final 340000 cents once risk scores apply."
        PRD §3.9: "The `adjustment_cents` is the final amount minus
        `provisional_paid_cents`, with a negative value signaling a recovery owed by the
        MCO."

        Design: Difficulty/dual_variant_calc/capitation_provisional_vs_final_divergence
        """
        fx = self._setup_risk_scored_cycle()
        statement = fx["statement"]
        assert statement["member_months"] == 4
        assert statement["provisional_paid_cents"] == 270000, "3 * 50000 + 1 * 120000 at risk 1.0"

        reconciled = validate_success(api_client.reconcile_statement(statement["id"], FIN))
        # per-member lines: round(50000*0.8)=40000, round(50000*1.2)=60000,
        # round(50000*0.0)=0, round(120000*2.0)=240000
        assert reconciled["final_amount_cents"] == 340000
        assert reconciled["adjustment_cents"] == 70000, "final - provisional: variants diverge on identical member-months"
        assert reconciled["withhold_applied"] is False, "no FAILED audit for the cycle"

    def test_capitation_reconcile_consumes_snapshots(self):
        """PRD §3.9: "Reconciliation moves the statement `PROVISIONAL_ISSUED →
        RECONCILED` (terminal) and flips every snapshot of the cycle
        `COMPUTED → APPLIED`."
        PRD §3.9: "Pass three normalizes: each `normalized_score` is the member's raw
        score divided by that average, rounded half up to four decimal places"

        Design: Difficulty/dual_variant_calc/capitation_provisional_vs_final_divergence
        """
        fx = self._setup_risk_scored_cycle(program_name="P-CAP2")
        cycle = fx["cycle"]
        members = fx["members"]
        before, _ = validate_paginated(api_client.list_risk_snapshots(FIN, params={"cycle_id": cycle["id"]}))
        expected = {members[0]["id"]: 0.8, members[1]["id"]: 1.2, members[2]["id"]: 0.0, members[3]["id"]: 2.0}
        for snap in before:
            assert snap["status"] == "COMPUTED"
            assert snap["normalized_score"] == pytest.approx(expected[snap["member_id"]]), (
                f"average raw is 1.0, so normalized equals raw for member {snap['member_id']}"
            )

        reconciled = validate_success(api_client.reconcile_statement(fx["statement"]["id"], FIN))
        assert reconciled["status"] == "RECONCILED"
        assert reconciled["provisional_paid_cents"] == 270000
        assert reconciled["final_amount_cents"] == 340000

        after, _ = validate_paginated(api_client.list_risk_snapshots(FIN, params={"cycle_id": cycle["id"]}))
        assert len(after) == 4
        assert all(s["status"] == "APPLIED" for s in after), "reconcile flips every snapshot COMPUTED → APPLIED"


class TestPerMemberRoundingOrder:
    def _setup_rounding_cycle(self, program_name="P-RND"):
        """TANF@33333; 3 members with raw scores 0.8 / 0.8 / 1.4 (average 1.0)."""
        program = create_program(name=program_name)
        create_rate_schedule(program["id"], aid_category="TANF", pmpm_cents=33333)
        cycle = create_cycle(program["id"])
        m1 = create_member(program["id"], aid_category="TANF")
        m2 = create_member(program["id"], aid_category="TANF")
        m3 = create_member(program["id"], aid_category="TANF")
        provider = create_provider(program["id"])
        _acknowledge_with_diagnoses(program["id"], cycle["id"], provider["id"], m1, "E1", ["E11"])
        _acknowledge_with_diagnoses(program["id"], cycle["id"], provider["id"], m2, "E2", ["E11"])
        _acknowledge_with_diagnoses(program["id"], cycle["id"], provider["id"], m3, "E3", ["F32", "N18"])
        validate_success(api_client.compute_risk_scores(cycle["id"], FIN))
        statement = create_statement(cycle["id"])
        return {"program": program, "cycle": cycle, "statement": statement}

    def test_capitation_per_member_rounding_then_sum(self):
        """PRD §3.9: "The final amount follows a pinned rounding order in which
        per-member rounding happens first: each member-month's line is that member's
        `pmpm_cents` multiplied by the member's `normalized_score` — zero for members
        with no scored encounters unless the zero-average rule lifted everyone to 1.0 —
        rounded half up to a whole cent; the lines are then summed into a subtotal.
        Summing unrounded products first and rounding once is forbidden, because it
        produces different cents."

        Design: Difficulty/combinatorial_formula/capitation_per_member_rounding_then_sum
        """
        fx = self._setup_rounding_cycle()
        statement = fx["statement"]
        assert statement["provisional_paid_cents"] == 99999, "3 * 33333"

        reconciled = validate_success(api_client.reconcile_statement(statement["id"], FIN))
        # round_half_up(33333*0.8)=26666 (twice) + round_half_up(33333*1.4)=46666
        assert reconciled["final_amount_cents"] == 99998, (
            "per-member rounding yields 26666 + 26666 + 46666; sum-then-round would give 99999"
        )
        assert reconciled["adjustment_cents"] == -1
        assert reconciled["status"] == "RECONCILED"

    def test_capitation_per_member_rounding_observed_via_get(self):
        """PRD §3.9: "The final amount follows a pinned rounding order in which
        per-member rounding happens first: each member-month's line is that member's
        `pmpm_cents` multiplied by the member's `normalized_score` — zero for members
        with no scored encounters unless the zero-average rule lifted everyone to 1.0 —
        rounded half up to a whole cent; the lines are then summed into a subtotal."
        PRD §3.9: "When the cycle's audit determination is `FAIL`, a five-percent
        withhold applies: the subtotal is multiplied by 0.95 and rounded half up to a
        whole cent to yield `final_amount_cents`, with `withhold_applied` set true; on
        any other outcome the subtotal itself is the final amount and `withhold_applied`
        stays false."

        Design: Difficulty/combinatorial_formula/capitation_per_member_rounding_then_sum
        """
        fx = self._setup_rounding_cycle(program_name="P-RND2")
        validate_success(api_client.reconcile_statement(fx["statement"]["id"], FIN))
        fetched = validate_success(api_client.get_statement(fx["statement"]["id"], FIN))
        assert fetched["provisional_paid_cents"] == 99999
        assert fetched["final_amount_cents"] == 99998
        assert fetched["adjustment_cents"] == -1
        assert fetched["withhold_applied"] is False
        assert fetched["status"] == "RECONCILED"


class TestRiskNormalization:
    def test_risk_normalization_zero_average_guard(self):
        """PRD §3.9: "Pass three normalizes: each `normalized_score` is the member's
        raw score divided by that average, rounded half up to four decimal places, and
        when the average itself is zero every member normalizes to exactly 1.0."
        PRD §3.9: "The snapshots are born `COMPUTED`, the run stamps the cycle's
        `risk_computed_at`"

        Design: Corner/calculations/risk_normalization_zero_average_guard
        """
        program = create_program(name="P-CALC3")
        cycle = create_cycle(program["id"])
        create_member(program["id"], aid_category="TANF")
        create_member(program["id"], aid_category="TANF")
        snapshots = validate_success(api_client.compute_risk_scores(cycle["id"], FIN))
        assert len(snapshots) == 2
        for snap in snapshots:
            assert snap["raw_score"] == pytest.approx(0)
            assert snap["normalized_score"] == pytest.approx(1.0), "zero-average guard lifts every member to 1.0"
            assert snap["status"] == "COMPUTED"
        cycle_after = get_success_data(api_client.get_cycle(cycle["id"], STATE))
        assert cycle_after["risk_computed_at"] is not None


class TestMemberMonths:
    def test_member_months_partial_overlap_counts_full_month(self):
        """PRD §3.9: "Issuance computes `member_months` as the count of members whose
        enrollment interval overlaps the cycle's half-open window by at least one day,
        and prices the `provisional_paid_cents` with risk pinned at 1.0 for every
        member: each member-month contributes its category's `pmpm_cents` (rounding half
        up to a whole cent at 1.0 changes nothing), so the provisional total is the
        plain sum of applicable per-member rates."

        Design: Corner/calculations/member_months_partial_overlap_counts_full_month
        """
        program = create_program(name="P-CALC5")
        create_rate_schedule(program["id"], aid_category="TANF", pmpm_cents=50000)
        cycle = create_cycle(program["id"])
        # Mid-month enrollee: overlaps the August window and counts a full month.
        create_member(program["id"], aid_category="TANF", enrolled_from="2026-08-15")
        # July-only member: enrollment ended before the window opens.
        mb = create_member(program["id"], aid_category="TANF", enrolled_from="2026-07-01")
        get_success_data(api_client.disenroll_member(mb["id"], {"disenrolled_date": "2026-07-31"}, OPS))

        statement = validate_success(api_client.create_statement({"cycle_id": cycle["id"]}, FIN), expected_status=201)
        assert statement["member_months"] == 1
        assert statement["provisional_paid_cents"] == 50000


class TestStatementGuards:
    def test_statement_create_without_rate_coverage_returns_rate_not_found(self):
        """PRD §3.9: "Two guards apply in pipeline order: rate coverage is verified
        first — every aid category with at least one enrolled-overlapping member must
        have a rate schedule whose closed effective window covers the cycle's window
        start date, or issuance fails with `ERR_RATE_NOT_FOUND` — and then the
        one-statement-per-cycle constraint, a duplicate drawing `ERR_STATEMENT_EXISTS`."

        Design: Corner/validations/statement_create_without_rate_coverage_returns_rate_not_found
        """
        program = create_program(name="P-V6")
        create_rate_schedule(program["id"], aid_category="TANF", pmpm_cents=50000)
        cycle = create_cycle(program["id"])
        create_member(program["id"], aid_category="EXPANSION")
        resp = api_client.create_statement({"cycle_id": cycle["id"]}, FIN)
        validate_error(resp, ApiErrorId.ERR_RATE_NOT_FOUND)
        _data, meta = validate_paginated(api_client.list_statements(FIN, params={"cycle_id": cycle["id"]}))
        assert meta["total_count"] == 0, "no statement may persist"

    def test_statement_reconcile_twice_returns_invalid_state(self):
        """PRD §3.9: "Reconciliation by `McoFinance` requires a `PROVISIONAL_ISSUED`
        statement (`ERR_INVALID_STATE_TRANSITION` otherwise) and requires risk scores to
        exist — a null `risk_computed_at` is rejected with `ERR_SNAPSHOTS_REQUIRED`."
        PRD §3.9: "Reconciliation moves the statement `PROVISIONAL_ISSUED → RECONCILED`
        (terminal)"

        Design: Corner/state_machines/statement_reconcile_twice_returns_invalid_state
        """
        program = create_program(name="P-SM14")
        create_rate_schedule(program["id"], aid_category="TANF", pmpm_cents=50000)
        cycle = create_cycle(program["id"])
        create_member(program["id"], aid_category="TANF")
        validate_success(api_client.compute_risk_scores(cycle["id"], FIN))
        statement = create_statement(cycle["id"])
        reconciled = validate_success(api_client.reconcile_statement(statement["id"], FIN))
        assert reconciled["status"] == "RECONCILED"
        assert reconciled["final_amount_cents"] == 50000, "zero-average guard: normalized 1.0 for the only member"

        resp = api_client.reconcile_statement(statement["id"], FIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_success_data(api_client.get_statement(statement["id"], FIN))
        assert after["status"] == "RECONCILED"
        assert after["final_amount_cents"] == 50000
