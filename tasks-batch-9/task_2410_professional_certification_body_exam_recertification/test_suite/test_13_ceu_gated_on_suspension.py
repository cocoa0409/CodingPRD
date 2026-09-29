"""A credit claim names only a cycle, yet a disciplinary case decides its fate."""

import pytest

from test_helpers import ApiErrorId
from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_success
from test_helpers.test_users import (
    ETHICS_OFFICER_1_ID,
    ETHICS_OFFICER_2_ID,
    make_ethics_officer_headers,
)

DECIDER = make_ethics_officer_headers(ETHICS_OFFICER_2_ID)
STRICT_PROGRAM = {"ceu_credit_accrual_basis": "STRICT_CYCLE"}
ALLEGATION = {"allegation_type": "ETHICS_VIOLATION",
              "description": "Undisclosed conflict of interest"}
SANCTION_MONTHS = 6
SUSPENSION_ENDS = "2027-02-10T00:00:00Z"
BARRED_CLAIM = {"activity_date": "2026-09-15T00:00:00Z", "category": "LIVE_INSTRUCTION",
                "provider": "State Chapter Seminar", "contact_hours": 12.0}
POST_SUSPENSION_CLAIM = {"activity_date": "2027-02-10T00:00:00Z",
                         "category": "LIVE_INSTRUCTION",
                         "provider": "State Chapter Seminar", "contact_hours": 12.0}


def _suspended_holder(api):
    """A holder with an open cycle and no credit, suspended for six months by a
    decided case.
    """
    state = fx.pipeline_through_certificant(api, program_overrides=STRICT_PROGRAM)
    case = fx.case_awaiting_decision(api, state, opener_user_id=ETHICS_OFFICER_1_ID,
                                    **ALLEGATION)
    decided = validate_success(api.decide_case(
        case["id"], f.decide_case_payload("SANCTIONED", sanction_months=SANCTION_MONTHS,
                                          decision_note="Six-month suspension"),
        DECIDER), 200)
    return state, decided


class TestSanctionClosesTheCreditGate:
    """The sanction suspends the holder without touching the cycle."""

    def test_sanction_suspends_the_holder_and_withholds_publication(self, api):
        """The decision closes the case and moves the credential to SUSPENDED with a
        release date six months out.

        PRD §3.12: "`SANCTIONED` requires the respondent's `status` to be `ACTIVE` —
        otherwise `ERR_CERTIFICANT_NOT_ACTIVE` — and moves it `ACTIVE → SUSPENDED`,
        setting `suspension_until` to the current logical-clock instant advanced by
        `sanction_months` months, recomputing `publication_status` to `WITHHELD`, and
        incrementing the certificant's `version` by 1".

        Design: Difficulty/cross_entity_state_dependency/ceu_submission_gated_on_certificant_suspension_produced_by_a_disciplinary_sanction
        """
        state, decided = _suspended_holder(api)

        assert decided["status"] == "CLOSED"
        assert decided["outcome"] == "SANCTIONED"
        assert decided["sanction_months"] == SANCTION_MONTHS

        certificant = fx.read_certificant(api, state.certificant_id)
        assert certificant["status"] == "SUSPENDED"
        assert str(certificant["suspension_until"]).startswith("2027-02-10")
        assert certificant["publication_status"] == "WITHHELD"
        ax.assert_publication_status_agrees_with_status(certificant)

    def test_the_sanction_leaves_the_cycle_open_and_empty(self, api):
        """A suspension is not a revocation: the recertification window survives it
        untouched.

        PRD §3.12: "**Hop two:** because the certificant was revoked, every
        recertification cycle of that certificant whose `status` is `OPEN`,
        `SATISFIED`, or `LAPSED` moves to `VOID`, which is terminal."

        PRD §3.11: "A `CEU`-path cycle is `SATISFIED` exactly when its
        `credits_applied` is greater than or equal to its `required_credits`, with
        exact equality satisfying".

        Design: Difficulty/cross_entity_state_dependency/ceu_submission_gated_on_certificant_suspension_produced_by_a_disciplinary_sanction
        """
        state, _decided = _suspended_holder(api)

        cycle = fx.read_cycle(api, state.cycle_id)
        assert cycle["status"] == "OPEN"
        assert float(cycle["credits_applied"]) == pytest.approx(0.00, abs=0.01)
        assert float(cycle["required_credits"]) == pytest.approx(12.00, abs=0.01)
        ax.assert_recertification_cycle(cycle)

    def test_credit_claim_is_refused_while_the_holder_is_suspended(self, api):
        """The cycle is open and the activity date is inside its window, and the claim
        is still refused on the parent's status, leaving no row behind.

        PRD §2.7: "**Certificant active.** The owning certificant's `status` is
        `ACTIVE`, not `SUSPENDED`, `EXPIRED`, or `REVOKED` → otherwise
        `ERR_CERTIFICANT_NOT_ACTIVE` (409). Applies to claiming credit against a
        cycle, closing a cycle, and reviewing a credit claim."

        Design: Difficulty/cross_entity_state_dependency/ceu_submission_gated_on_certificant_suspension_produced_by_a_disciplinary_sanction
        """
        state, _decided = _suspended_holder(api)

        refused = api.claim_ceu_activity(state.cycle_id, f.claim_ceu_payload(**BARRED_CLAIM),
                                         state.owner_headers)

        validate_error(refused, ApiErrorId.ERR_CERTIFICANT_NOT_ACTIVE.value, 409)
        assert fx.read_activities_of(api, state.cycle_id) == []


class TestReactivationReopensTheCreditGate:
    """Only the maintenance run can end the suspension."""

    def test_the_run_reactivates_the_holder_once_the_clock_reaches_release(self, api):
        """Setting the clock is inert; the checkpoint is what restores the credential,
        and it reports the reactivation without lapsing the still-in-window cycle.

        PRD §3.13: "**Step four — reactivations.** Every certificant whose `status` is
        `SUSPENDED` and whose `suspension_until` the logical clock has reached moves
        back to `ACTIVE`, with `suspension_until` cleared and `publication_status`
        recomputed to `PUBLISHED`."

        PRD §3.13: "The run answers with a report object rather than an entity:
        `run_at` records the logical-clock instant of the run, and six identifier lists
        record what it touched".

        Design: Difficulty/cross_entity_state_dependency/ceu_submission_gated_on_certificant_suspension_produced_by_a_disciplinary_sanction
        """
        state, _decided = _suspended_holder(api)
        fx.set_clock(api, SUSPENSION_ENDS)

        report = fx.run_maintenance(api)

        ax.assert_maintenance_run_report(report)
        assert report["reactivated_certificant_ids"] == [state.certificant_id]
        assert report["lapsed_cycle_ids"] == []

        certificant = fx.read_certificant(api, state.certificant_id)
        assert certificant["status"] == "ACTIVE"
        assert certificant["suspension_until"] is None
        assert certificant["publication_status"] == "PUBLISHED"

    def test_the_same_claim_is_accepted_after_reactivation(self, api):
        """The identical submission that was refused is now accepted, uncounted until
        review, with an hour of live instruction worth one credit.

        PRD §3.11: "The multipliers reflect the effort each activity type represents: an
        hour of `LIVE_INSTRUCTION` is worth 1.0 credits, an hour of `SELF_STUDY` is
        worth 0.5, an hour spent `PRESENTING` is worth 2.0, an hour spent on
        `PUBLICATION` is worth 5.0, and an hour of `VOLUNTEER` service is worth 0.25."

        Design: Difficulty/cross_entity_state_dependency/ceu_submission_gated_on_certificant_suspension_produced_by_a_disciplinary_sanction
        """
        state, _decided = _suspended_holder(api)
        fx.set_clock(api, SUSPENSION_ENDS)
        fx.run_maintenance(api)

        claimed = validate_success(api.claim_ceu_activity(
            state.cycle_id, f.claim_ceu_payload(**POST_SUSPENSION_CLAIM),
            state.owner_headers), 201)

        assert claimed["status"] == "SUBMITTED"
        assert float(claimed["credits_awarded"]) == pytest.approx(12.00, abs=0.01)
        assert claimed["counted"] is False
        ax.assert_credit_precision(claimed["credits_awarded"])

    def test_approval_after_reactivation_satisfies_the_cycle(self, api):
        """With the holder active again the reviewer can approve, the credit counts, and
        the cycle re-derives to SATISFIED.

        PRD §3.11: "In summary, `counted` is true exactly when an activity's `status` is
        `APPROVED` or `VERIFIED` **and** its `activity_date` falls inside the cycle's
        accrual window; `SUBMITTED`, `REJECTED`, `AUDIT_SELECTED`, and `REVOKED`
        activities never count."

        PRD §3.11: "So an approval that carries a cycle over the line bubbles it `OPEN →
        SATISFIED`".

        Design: Difficulty/cross_entity_state_dependency/ceu_submission_gated_on_certificant_suspension_produced_by_a_disciplinary_sanction
        """
        state, _decided = _suspended_holder(api)
        fx.set_clock(api, SUSPENSION_ENDS)
        fx.run_maintenance(api)

        approved = fx.approved_ceu(api, state, **POST_SUSPENSION_CLAIM)

        assert approved["status"] == "APPROVED"
        assert approved["counted"] is True
        assert float(approved["credits_counted"]) == pytest.approx(12.00, abs=0.01)

        cycle = fx.read_cycle(api, state.cycle_id)
        assert float(cycle["credits_applied"]) == pytest.approx(12.00, abs=0.01)
        assert cycle["status"] == "SATISFIED"
        ax.assert_credits_applied_matches_counted_children(
            cycle, fx.read_activities_of(api, state.cycle_id))
