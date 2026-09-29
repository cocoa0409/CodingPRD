"""Machines that revisit their own earlier states without rewinding history."""

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_field_values,
    assert_fields_null,
    assert_reserve_conserved,
)

# The determination lands at 2026-03-01, so report_due_at is that instant plus
# 240 hours; the first filing at 2026-03-13 is two days late and the refiling at
# 2026-03-23 is twelve days late against the very same deadline.
DETERMINATION_CLOCK = "2026-03-01T00:00:00Z"
REPORT_DUE_AT = "2026-03-11T00:00:00"
FIRST_SUBMIT_CLOCK = "2026-03-13T00:00:00Z"
REFILE_CLOCK = "2026-03-23T00:00:00Z"

ASSESSED_PENALTY_CENTS = 5500000

# Three agency offers interleaved with two respondent counters. Each row is the
# amount, the offering party, the status it leaves behind, and the reserve split
# that status implies.
OFFER_SEQUENCE = (
    (5500000, "AGENCY", "OFFER_MADE", 5500000, 0),
    (3000000, "RESPONDENT", "COUNTERED", 0, 5500000),
    (4500000, "AGENCY", "OFFER_MADE", 4500000, 1000000),
    (4000000, "RESPONDENT", "COUNTERED", 0, 5500000),
    (4200000, "AGENCY", "OFFER_MADE", 4200000, 1300000),
)

# The proposal the agency sends back, and the one the officer files in its place.
REPAIR_PROPOSAL = {
    "corrective_action_type": "REPAIR",
    "corrective_action_summary": "Field repair kit mailed to registered owners.",
}

REFUND_PROPOSAL = {
    "corrective_action_type": "REFUND",
    "corrective_action_summary": (
        "Full purchase-price refund plus a prepaid return label for every unit "
        "in commerce."
    ),
}


def _instant(value):
    """The second-resolution prefix of an ISO 8601 instant."""
    return str(value)[:19]


def _table_offer(api, case_id, amount_cents, offered_by):
    """Table one offer against the case's freshest version."""
    case = fx.get_penalty_case(api, case_id)
    return fx.make_offer(api, case_id, amount_cents, offered_by, case["version"])


class TestPenaltyNegotiationCycle:
    """A negotiation that revisits OFFER_MADE, COUNTERED and ASSESSMENT_OPEN."""

    def _case_at_round_five(self, api):
        """A penalty docket standing in OFFER_MADE after five recorded offers."""
        env = fx.penalty_case_on_report_env(
            api,
            violation_count=4,
            clock=DETERMINATION_CLOCK,
            submit_clock=FIRST_SUBMIT_CLOCK,
        )
        for amount_cents, offered_by, _status, _reserved, _available in OFFER_SEQUENCE:
            _table_offer(api, env["case_id"], amount_cents, offered_by)
        return env

    def test_the_case_walks_offer_made_and_countered_repeatedly(self, api):
        """Five offers traverse the same pair of states and re-cut the reserve each time.

        The contract states: "A legal offer increments `current_offer_round` by 1,
        overwrites `current_offer_cents` with `amount_cents` and `current_offer_by`
        with `offered_by`, moves the case's `status` accordingly —
        `ASSESSMENT_OPEN → OFFER_MADE` or `COUNTERED → OFFER_MADE` for an agency
        offer, `OFFER_MADE → COUNTERED` for a respondent offer". The two
        directions split the reserve differently: "An `AGENCY` offer commits the
        money the office is prepared to settle for: `reserved_cents` becomes
        `amount_cents` and `available_cents` becomes `assessed_penalty_cents` minus
        `amount_cents`. A `RESPONDENT` counter is not the office's own commitment,
        so it releases the agency reserve entirely: `reserved_cents` returns to 0
        and `available_cents` returns to the full `assessed_penalty_cents`."

        Design: Difficulty/non_linear_state_machine/penalty_negotiation_cycles_offer_made_countered_then_reopens_without_rewinding_round
        """
        env = fx.penalty_case_on_report_env(
            api,
            violation_count=4,
            clock=DETERMINATION_CLOCK,
            submit_clock=FIRST_SUBMIT_CLOCK,
        )

        for index, spec in enumerate(OFFER_SEQUENCE, start=1):
            amount_cents, offered_by, status, reserved, available = spec
            case = _table_offer(api, env["case_id"], amount_cents, offered_by)

            assert_field_values(
                case,
                status=status,
                current_offer_round=index,
                current_offer_cents=amount_cents,
                current_offer_by=offered_by,
                reserved_cents=reserved,
                available_cents=available,
                assessed_penalty_cents=ASSESSED_PENALTY_CENTS,
            )
            assert_reserve_conserved(case)

    def test_withdrawal_reopens_assessment_open_without_refunding_the_round(
        self, api
    ):
        """Re-entering the initial state leaves the consumed rounds consumed.

        The contract states: "`WITHDRAWN` returns the case `OFFER_MADE →
        ASSESSMENT_OPEN`, clears `current_offer_cents` and `current_offer_by` back
        to null, and compensates the reserve exactly by setting `reserved_cents` to
        0 and `available_cents` to `assessed_penalty_cents`. It pointedly does
        **not** give the round back: a withdrawn offer still consumed a round, so
        `current_offer_round` is left where it stands and six withdrawn offers
        exhaust the negotiation just as surely as six live ones." The counter is
        one-way by construction: "The round counter is monotonic: it counts every
        offer entered into the record regardless of which side made it, is never
        decremented, and is capped at 6."

        Design: Difficulty/non_linear_state_machine/penalty_negotiation_cycles_offer_made_countered_then_reopens_without_rewinding_round
        """
        env = self._case_at_round_five(api)

        fx.resolve_offer(
            api,
            env["case_id"],
            "WITHDRAWN",
            note="Agency withdraws the standing offer pending further technical review.",
        )

        case = fx.get_penalty_case(api, env["case_id"])
        assert_field_values(
            case,
            status="ASSESSMENT_OPEN",
            current_offer_round=5,
            reserved_cents=0,
            available_cents=ASSESSED_PENALTY_CENTS,
            assessed_penalty_cents=ASSESSED_PENALTY_CENTS,
        )
        assert_fields_null(
            case,
            "current_offer_cents",
            "current_offer_by",
            "consent_agreement_total_cents",
        )
        assert_reserve_conserved(case)

    def test_a_sixth_offer_is_still_legal_after_the_withdrawal(self, api):
        """The reopened case has one round of budget left, not a fresh six.

        The contract states: "Next, `current_offer_round` must be strictly less
        than 6, otherwise `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` (HTTP 409) — the
        parties get six rounds and no more."

        Design: Difficulty/non_linear_state_machine/penalty_negotiation_cycles_offer_made_countered_then_reopens_without_rewinding_round
        """
        env = self._case_at_round_five(api)
        fx.resolve_offer(api, env["case_id"], "WITHDRAWN")

        case = _table_offer(api, env["case_id"], 4100000, "AGENCY")

        assert_field_values(
            case,
            status="OFFER_MADE",
            current_offer_round=6,
            current_offer_cents=4100000,
            current_offer_by="AGENCY",
            reserved_cents=4100000,
            available_cents=1400000,
        )
        assert_reserve_conserved(case)


class TestSectionReportRevisionLoop:
    """A statutory report that re-enters DRAFT from two states downstream."""

    def _returned_and_revised_report(self, api):
        """A report filed late, returned for information and put back into draft."""
        env = fx.submitted_report_env(
            api,
            clock=DETERMINATION_CLOCK,
            submit_clock=FIRST_SUBMIT_CLOCK,
            report=REPAIR_PROPOSAL,
        )
        env["first_filing"] = env["report"]
        fx.review_section_report(
            api,
            env["report_id"],
            "RETURNED_FOR_INFO",
            note="Repair kit does not address the weld itself; propose a refund remedy.",
        )
        env["revised"] = fx.revise_section_report(
            api, env["report_id"], **REFUND_PROPOSAL
        )
        return env

    def test_returning_the_report_reenters_draft_and_keeps_the_first_surcharge(
        self, api
    ):
        """The loop back to DRAFT clears submitted_at but carries the old figures.

        The contract states: "A report in `RETURNED_FOR_INFO` may be returned to
        `DRAFT`, optionally amending `corrective_action_type` and
        `corrective_action_summary` — each supplied value overwrites the stored
        one, and omitting both leaves the proposal as it was. `submitted_at` is
        reset to null while `days_late` and `late_surcharge_cents` keep their
        previous values until the next filing recomputes them."

        Design: Difficulty/non_linear_state_machine/section_report_returned_for_info_loops_through_draft_and_raises_surcharge
        """
        env = self._returned_and_revised_report(api)

        assert_field_values(
            env["first_filing"],
            status="SUBMITTED",
            corrective_action_type="REPAIR",
            days_late=2,
            late_surcharge_cents=500000,
        )
        assert _instant(env["first_filing"]["submitted_at"]) == "2026-03-13T00:00:00"

        report = fx.get_section_report(api, env["report_id"])
        assert_field_values(
            report,
            status="DRAFT",
            corrective_action_type="REFUND",
            days_late=2,
            late_surcharge_cents=500000,
        )
        assert_fields_null(report, "submitted_at")

    def test_refiling_rescores_lateness_against_the_same_unchanged_deadline(
        self, api
    ):
        """The second filing replaces two late days with twelve, raising the charge.

        The contract states: "The cycle `DRAFT → SUBMITTED → RETURNED_FOR_INFO →
        DRAFT` may repeat, and because each filing re-scores lateness against the
        *same* unchanged `report_due_at`, a second late filing can only raise the
        surcharge, never lower it." The charge itself follows: "When `days_late` is
        0 the `late_surcharge_cents` is 0; otherwise it is 250,000 cents per late
        day, capped at 5,000,000 cents in total, so the charge is the smaller of
        the per-day product and the cap."

        Design: Difficulty/non_linear_state_machine/section_report_returned_for_info_loops_through_draft_and_raises_surcharge
        """
        env = self._returned_and_revised_report(api)

        fx.set_clock(api, REFILE_CLOCK)
        refiled = fx.submit_section_report(api, env["report_id"])

        assert_field_values(
            refiled,
            status="SUBMITTED",
            corrective_action_type="REFUND",
            days_late=12,
            late_surcharge_cents=3000000,
        )
        assert _instant(refiled["submitted_at"]) == "2026-03-23T00:00:00"
        assert refiled["late_surcharge_cents"] != 500000, (
            "the surcharge is recomputed on refiling, not retained"
        )
        assert refiled["late_surcharge_cents"] != 3500000, (
            "surcharges do not accumulate across successive filings"
        )

        evaluation = fx.get_evaluation(api, env["evaluation_id"])
        assert _instant(evaluation["report_due_at"]) == REPORT_DUE_AT, (
            "the revision loop must not extend the statutory deadline"
        )
