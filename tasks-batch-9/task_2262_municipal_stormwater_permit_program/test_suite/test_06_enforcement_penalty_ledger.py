"""The penalty ledger: the self-excluding prior total and the rescission invariant."""

import pytest

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_cents, assert_penalty_derivation


class TestEscalationMultiplierExcludesItsOwnRow:
    """An action's own previous penalty never feeds its new multiplier."""

    @pytest.fixture
    def sole_notice(self):
        """One NOTICE_OF_VIOLATION at 20 violation days, past its cooling-off."""
        program = fx.setup_active_program()
        site = fx.setup_site_with_approved_plan(
            program["term_id"],
            esc_plan_reference="ESC-A-1",
            site_name="SITE-A",
            operator_name="Northline Builders",
            disturbed_acres=1.50,
        )
        action = fx.issue_enforcement_action(
            "NOTICE_OF_VIOLATION", construction_site_id=site["id"], violation_days=20
        )
        fx.set_clock("2026-08-16T00:00:00Z")
        return {"term_id": program["term_id"], "site": site, "action": action}

    def test_01_the_first_action_on_a_subject_is_assessed_at_the_bare_multiplier(
        self, sole_notice
    ):
        """20 days on a notice of violation is 65000 cents at multiplier 1.00.

        PRD: "`penalty_cents` is then the ladder base for the action's current
        `action_type` — 25000 cents for `NOTICE_OF_VIOLATION`, 50000 cents for
        `ADMINISTRATIVE_ORDER`, 100000 cents for `CIVIL_PENALTY` — plus 2000 cents
        for each of the `billable_violation_days`, with that sum multiplied by
        `escalation_multiplier` and the product rounded to whole cents."

        Design: Difficulty/combinatorial_formula/penalty_multiplier_excludes_the_escalating_action_itself
        """
        assert_penalty_derivation(
            sole_notice["action"],
            action_type="NOTICE_OF_VIOLATION",
            billable_violation_days=20,
            prior_assessed_total_cents=0,
            escalation_multiplier=1.00,
            penalty_cents=65000,
        )
        assert sole_notice["action"]["status"] == "ISSUED", "a new action starts ISSUED"

    def test_02_escalation_recomputes_at_multiplier_one_because_the_row_excludes_itself(
        self, sole_notice
    ):
        """The escalated order is 100000 cents, not the self-inclusive 150000.

        PRD: "Second, `prior_assessed_total_cents` is the sum of `penalty_cents`
        over the *other* enforcement actions on the same subject whose `status` is
        `ISSUED`, `ESCALATED` or `CLOSED`, excluding this action's own row and
        frozen before this row's own penalty is written."

        Design: Difficulty/combinatorial_formula/penalty_multiplier_excludes_the_escalating_action_itself
        """
        escalated = fx.escalate_action(sole_notice["action"]["id"], violation_days=25)

        assert escalated["status"] == "ESCALATED", "escalation writes ESCALATED"
        assert_penalty_derivation(
            escalated,
            action_type="ADMINISTRATIVE_ORDER",
            billable_violation_days=25,
            prior_assessed_total_cents=0,
            escalation_multiplier=1.00,
            penalty_cents=100000,
        )
        assert escalated["penalty_cents"] != 150000, (
            "150000 is the result of feeding the action's own prior 65000 into its "
            "own multiplier"
        )
        assert escalated["escalation_count"] == 1, "the first escalation counts once"
        assert escalated["last_escalated_at"] is not None, (
            "escalation stamps last_escalated_at from the logical clock"
        )

    def test_03_the_term_ledger_moves_by_the_penalty_difference_only(self, sole_notice):
        """The ledger goes 65000 to 100000, not 65000 plus 100000.

        PRD: "A successful escalation recomputes `prior_assessed_total_cents`,
        `escalation_multiplier` and `penalty_cents`, adjusts the term's
        `total_assessed_penalty_cents` by the difference between the new penalty
        and the old one, increments `escalation_count` by one and stamps
        `last_escalated_at` from the logical clock."

        Design: Difficulty/combinatorial_formula/penalty_multiplier_excludes_the_escalating_action_itself
        """
        before = fx.read_term(sole_notice["term_id"])
        assert_cents(
            before["total_assessed_penalty_cents"], 65000, "total_assessed_penalty_cents"
        )

        fx.escalate_action(sole_notice["action"]["id"], violation_days=25)

        after = fx.read_term(sole_notice["term_id"])
        assert_cents(
            after["total_assessed_penalty_cents"], 100000, "total_assessed_penalty_cents"
        )
        assert after["total_assessed_penalty_cents"] != 165000, (
            "165000 would mean the escalation added a second penalty instead of "
            "adjusting by the difference"
        )


class TestRescissionConservesTheLedger:
    """Rescinding one row subtracts exactly what it added, and nothing else."""

    @pytest.fixture
    def two_actions_on_one_site(self):
        """A notice at 25000 and an order at 105000 on the same 2.50-acre site."""
        program = fx.setup_active_program()
        fx.report_progress(program["measures"]["CONSTRUCTION_RUNOFF"]["id"], 30)
        site = fx.setup_site_with_approved_plan(
            program["term_id"],
            esc_plan_reference="ESC-I-1",
            site_name="SITE-I",
            operator_name="Ironwood Contractors",
            disturbed_acres=2.50,
        )
        first = fx.issue_enforcement_action(
            "NOTICE_OF_VIOLATION", construction_site_id=site["id"], violation_days=0
        )
        second = fx.issue_enforcement_action(
            "ADMINISTRATIVE_ORDER", construction_site_id=site["id"], violation_days=10
        )
        return {
            "term_id": program["term_id"],
            "measure_id": program["measures"]["CONSTRUCTION_RUNOFF"]["id"],
            "site": site,
            "first": first,
            "second": second,
        }

    def test_04_the_ledger_starts_as_the_sum_of_the_two_rows(self, two_actions_on_one_site):
        """25000 plus 105000 is 130000, and two actions trip the runoff gate.

        PRD: "Issuance feeds the ledger and the derived counters. The new
        `penalty_cents` is added to the term's `total_assessed_penalty_cents`,
        which may push a `COMPILED` or `CERTIFIED` annual report back to `DRAFT`."

        Design: Difficulty/compensating_invariant/penalty_ledger_survives_rescission_without_retroactive_recomputation
        """
        assert_penalty_derivation(
            two_actions_on_one_site["second"],
            action_type="ADMINISTRATIVE_ORDER",
            billable_violation_days=10,
            prior_assessed_total_cents=25000,
            escalation_multiplier=1.50,
            penalty_cents=105000,
        )

        term = fx.read_term(two_actions_on_one_site["term_id"])
        assert_cents(
            term["total_assessed_penalty_cents"], 130000, "total_assessed_penalty_cents"
        )

        measure = fx.read_measure(two_actions_on_one_site["measure_id"])
        assert measure["enforcement_count"] == 2, "both actions reach the runoff measure"
        assert measure["goal_status"] == "BEHIND", (
            "two enforcement actions trip the construction runoff gate"
        )
        assert term["compliance_posture"] == "AT_RISK", (
            "exactly one behind measure leaves the term AT_RISK"
        )

    def test_05_rescission_subtracts_exactly_what_that_row_contributed(
        self, two_actions_on_one_site
    ):
        """The ledger falls from 130000 to 105000 and the row zeroes out.

        PRD: "From `ISSUED` or `ESCALATED`, and carrying a `reason`, rescission
        writes `RESCINDED` into `status`, stamps `rescinded_at`, records the reason
        in `rescinded_reason`, subtracts the action's `penalty_cents` from the
        term's `total_assessed_penalty_cents` and then sets `penalty_cents` to 0."

        Design: Difficulty/compensating_invariant/penalty_ledger_survives_rescission_without_retroactive_recomputation
        """
        rescinded = fx.rescind_action(
            two_actions_on_one_site["first"]["id"],
            reason="Issued against the wrong operator of record",
        )

        assert rescinded["status"] == "RESCINDED", "rescission writes RESCINDED"
        assert_cents(rescinded["penalty_cents"], 0, "penalty_cents")
        assert rescinded["rescinded_at"] is not None, "rescission stamps rescinded_at"
        assert rescinded["rescinded_reason"] == "Issued against the wrong operator of record", (
            "the reason is recorded on the rescinded action"
        )

        term = fx.read_term(two_actions_on_one_site["term_id"])
        assert_cents(
            term["total_assessed_penalty_cents"], 105000, "total_assessed_penalty_cents"
        )

    def test_06_the_sibling_action_is_never_retroactively_recomputed(
        self, two_actions_on_one_site
    ):
        """The order keeps its frozen 1.50 multiplier and its 105000 cents.

        PRD: "`RESCINDED` rows do not count toward the prior total, so a
        rescission lowers the multiplier of actions issued against that subject
        afterwards."

        Design: Difficulty/compensating_invariant/penalty_ledger_survives_rescission_without_retroactive_recomputation
        """
        fx.rescind_action(two_actions_on_one_site["first"]["id"])

        sibling = fx.read_action(two_actions_on_one_site["second"]["id"])
        assert_penalty_derivation(
            sibling,
            action_type="ADMINISTRATIVE_ORDER",
            billable_violation_days=10,
            prior_assessed_total_cents=25000,
            escalation_multiplier=1.50,
            penalty_cents=105000,
        )
        assert sibling["penalty_cents"] != 70000, (
            "70000 would mean the rescission retroactively re-multiplied a row "
            "assessed while the rescinded penalty still counted"
        )

    def test_07_the_rescission_clears_the_runoff_gate(self, two_actions_on_one_site):
        """One action left means the measure returns to MET and the term COMPLIANT.

        PRD: "It lowers the subject site's `open_enforcement_count` and the
        `CONSTRUCTION_RUNOFF` control measure's `enforcement_count`, recomputes
        that measure's `goal_status` — which is one of the two ways a tripped gate
        clears — recomputes the term's `compliance_posture`, and may push a
        `COMPILED` or `CERTIFIED` annual report back to `DRAFT`."

        Design: Difficulty/compensating_invariant/penalty_ledger_survives_rescission_without_retroactive_recomputation
        """
        fx.rescind_action(two_actions_on_one_site["first"]["id"])

        site = fx.read_site(two_actions_on_one_site["site"]["id"])
        assert site["open_enforcement_count"] == 1, (
            "one of the two actions is no longer open against the site"
        )

        measure = fx.read_measure(two_actions_on_one_site["measure_id"])
        assert measure["enforcement_count"] == 1, "the rescinded action leaves the count"
        assert measure["goal_status"] == "MET", (
            "with the gate cleared the measure returns to its attainment band"
        )

        term = fx.read_term(two_actions_on_one_site["term_id"])
        assert term["compliance_posture"] == "COMPLIANT", (
            "no behind measure leaves the term compliant again"
        )

    def test_08_a_later_action_reads_the_lowered_prior_total(self, two_actions_on_one_site):
        """The next notice is assessed against 105000 and multiplies by 2.25.

        PRD: "Third, `escalation_multiplier` is read from that prior total: 1.00
        when `prior_assessed_total_cents` is 0; 1.50 when it is greater than 0 but
        less than 100000 cents; and 2.25 when it is 100000 cents or more."

        Design: Difficulty/compensating_invariant/penalty_ledger_survives_rescission_without_retroactive_recomputation
        """
        fx.rescind_action(two_actions_on_one_site["first"]["id"])

        third = fx.issue_enforcement_action(
            "NOTICE_OF_VIOLATION",
            construction_site_id=two_actions_on_one_site["site"]["id"],
            violation_days=0,
        )

        assert_penalty_derivation(
            third,
            action_type="NOTICE_OF_VIOLATION",
            billable_violation_days=0,
            prior_assessed_total_cents=105000,
            escalation_multiplier=2.25,
            penalty_cents=56250,
        )
        assert third["prior_assessed_total_cents"] != 130000, (
            "a rescinded row must not be counted in a later action's prior total"
        )

    def test_09_the_ledger_always_equals_the_sum_of_the_rows(self, two_actions_on_one_site):
        """0 plus 105000 plus 56250 is the term's 161250.

        PRD: "The new `penalty_cents` is added to the term's
        `total_assessed_penalty_cents`, which may push a `COMPILED` or `CERTIFIED`
        annual report back to `DRAFT`."

        Design: Difficulty/compensating_invariant/penalty_ledger_survives_rescission_without_retroactive_recomputation
        """
        fx.rescind_action(two_actions_on_one_site["first"]["id"])
        fx.issue_enforcement_action(
            "NOTICE_OF_VIOLATION",
            construction_site_id=two_actions_on_one_site["site"]["id"],
            violation_days=0,
        )

        term = fx.read_term(two_actions_on_one_site["term_id"])
        assert_cents(
            term["total_assessed_penalty_cents"], 161250, "total_assessed_penalty_cents"
        )

        measure = fx.read_measure(two_actions_on_one_site["measure_id"])
        assert measure["enforcement_count"] == 2, (
            "the third action puts the runoff count back at two"
        )
        assert measure["goal_status"] == "BEHIND", "the gate is tripped once more"
        assert term["compliance_posture"] == "AT_RISK", (
            "one behind measure leaves the term AT_RISK again"
        )
