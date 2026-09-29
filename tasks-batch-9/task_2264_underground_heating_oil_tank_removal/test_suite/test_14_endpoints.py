"""Computed reads, the settlement action and the conditional reopening of sampling."""
import pytest

from test_helpers import (
    fixtures as fx,
    parse_instant,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import claim_decision_payload, soil_sample_payload
from test_helpers.test_users import COMPLIANCE_OFFICER, FIELD_TECHNICIAN


class TestProjectSummaryRead:
    def test_the_posture_snapshot_reports_the_projects_derived_figures(self, api):
        """PRD §3.1: "Alongside the ordinary single-project read, a computed posture snapshot is available to the `ProjectCoordinator`, the `LicensedSiteProfessional` and the `ComplianceOfficer`. It returns the project's `status`, its `contamination_class`, `approved_scope_cubic_yards`, `remediation_volume_cubic_yards`, `remediation_volume_basis`, `remediation_cost_cents`, `nfa_blockers`, the project's current `version`, and two convenience counts: `open_change_order_count`, the number of change orders on the project that are still in `DRAFT` or `SUBMITTED`, and `current_round_sample_count`, the number of soil samples whose `sampling_round` equals the project's current `sampling_round`."
        PRD §3.7: "Once the latch is true, `remediation_cost_cents` is the flat mobilization charge of 185,000 cents — one thousand eight hundred fifty dollars — plus the line total from step two."

        Design: Corner/endpoints/project_summary_computed_read_matches_the_derived_fields
        """
        ctx = fx.project_remediation_active_elevated()
        project = ctx["project"]

        summary = validate_success(
            api.get_tank_project_summary(project["id"], COMPLIANCE_OFFICER)
        )

        assert summary["status"] == "REMEDIATION_ACTIVE", (
            f"the snapshot must report the live status, got {summary['status']}"
        )
        assert summary["contamination_class"] == "ELEVATED", (
            f"the snapshot must report the live class, got {summary['contamination_class']}"
        )
        assert summary["approved_scope_cubic_yards"] == pytest.approx(8.0, abs=0.01), (
            "with no approved change order the scope is the baseline, got "
            f"{summary['approved_scope_cubic_yards']}"
        )
        assert summary["remediation_volume_cubic_yards"] == pytest.approx(
            25.93, abs=0.01
        ), (
            "one impacted point at 84 inches gives 25.93 cubic yards, got "
            f"{summary['remediation_volume_cubic_yards']}"
        )
        assert summary["remediation_volume_basis"] == "PROVISIONAL_GRID", (
            f"the grid estimate produced the figure, got {summary['remediation_volume_basis']}"
        )
        assert summary["remediation_cost_cents"] == 185000, (
            "the bare mobilization charge, with no change-order lines, got "
            f"{summary['remediation_cost_cents']}"
        )
        assert summary["nfa_blockers"] == [
            "CONTAMINATION_DISCLOSURE_NOT_ACKNOWLEDGED",
            "CONTAMINATION_NOT_CLEARED",
        ], (
            f"the snapshot republishes the blocker list, got {summary['nfa_blockers']}"
        )
        assert summary["open_change_order_count"] == 0, (
            f"no change order has been drafted, got {summary['open_change_order_count']}"
        )
        assert summary["current_round_sample_count"] == 1, (
            "one aliquot belongs to the round in progress, got "
            f"{summary['current_round_sample_count']}"
        )
        assert summary["version"] == project["version"], (
            "the snapshot reads the project rather than mutating it, got "
            f"{summary['version']} against {project['version']}"
        )


class TestClaimSettlement:
    #: Gross costs of 900,000 cents leave 818,500 eligible in New Jersey.
    CLAIMED_CENTS = 900000
    PAYMENT_INSTANT = "2026-08-06T13:00:00Z"

    def test_payment_settles_the_project_and_freezes_the_carrier_file(self, api):
        """PRD §3.9: "The claim transitions `APPROVED → PAID`, `paid_at` is stamped from the logical clock, `reimbursed_amount_cents` is set equal to `eligible_amount_cents`, and `unreimbursed_balance_cents` becomes 0. The project then advances `CLOSED_NFA → CLOSED_SETTLED`, every insurance notification on the project whose `status` is not `CLOSED` is transitioned to `CLOSED` with its allocation figures frozen, and the property's `open_project_count` is decremented by 1."
        PRD §3.9: "`CLOSED_SETTLED` is terminal, and it is the only satisfactory ending the workflow has."
        PRD §3.8: "A notification whose `status` is `CLOSED` is excluded from the rewrite entirely and never re-derives anything."

        Design: Corner/endpoints/claim_paid_action_settles_the_project_and_closes_the_carrier_file
        """
        ctx = fx.project_closed_nfa_with_approved_claim(
            claimed_costs_cents=self.CLAIMED_CENTS, notification_kind="FIRST_PARTY"
        )

        assert ctx["claim"]["eligible_amount_cents"] == 818500, (
            "900,000 gross under the 4,000,000-cent tier less the 50,000-cent "
            "deductible less the 31,500-cent fee is 818,500 cents, got "
            f"{ctx['claim']['eligible_amount_cents']}"
        )
        assert ctx["claim"]["status"] == "APPROVED", (
            f"the fund has approved the application, got {ctx['claim']['status']}"
        )

        paid = validate_success(
            api.decide_trust_fund_claim(
                ctx["claim"]["id"],
                claim_decision_payload(
                    "PAID", decision_note="trust fund disbursement wired"
                ),
                COMPLIANCE_OFFICER,
            ),
            200,
        )
        assert paid["status"] == "PAID", (
            f"the disbursement is recorded on the claim, got {paid['status']}"
        )
        assert paid["reimbursed_amount_cents"] == 818500, (
            "the whole eligible amount was disbursed, got "
            f"{paid['reimbursed_amount_cents']}"
        )
        assert paid["unreimbursed_balance_cents"] == 0, (
            f"nothing is left outstanding, got {paid['unreimbursed_balance_cents']}"
        )
        assert parse_instant(paid["paid_at"]) == parse_instant(
            self.PAYMENT_INSTANT
        ), (
            f"the payment instant comes from the logical clock, got {paid['paid_at']}"
        )

        assert fx.read_project(ctx["project"]["id"])["status"] == "CLOSED_SETTLED", (
            "payment is the only route into the terminal settled state"
        )
        assert fx.read_notification(ctx["notification"]["id"])["status"] == "CLOSED", (
            "the carrier file is closed with its allocation frozen"
        )
        assert fx.read_property(ctx["property"]["id"])["open_project_count"] == 0, (
            "the property's open-project tally falls back to zero"
        )


class TestConditionalReopeningOfSampling:
    def test_a_new_round_cannot_open_while_a_change_order_is_unsettled(self, api):
        """PRD §3.6: "That reopening is blocked while remediation scoping is unsettled: if the project has any `RemediationChangeOrder` still in `DRAFT` or `SUBMITTED`, the request is refused."
        PRD §3.6: "When the project stands at `REMEDIATION_ACTIVE`, the first sample created transitions the project `REMEDIATION_ACTIVE → SAMPLING`: `sampling_round` increments by 1, and it is the *incremented* value that the new sample records as its own `sampling_round`."
        PRD §2.11: "9. **State legality** — the target resource, and the project behind it, must be in a state from which the requested operation is declared. For project-targeted operations the code is `ERR_PROJECT_STATE_INVALID` (409); for other targets the entity-specific state code is used — `ERR_DISCLOSURE_STATE_INVALID`, `ERR_PERMIT_STATE_INVALID`, `ERR_WORK_ORDER_STATE_INVALID`, `ERR_SAMPLE_STATE_INVALID`, `ERR_CHANGE_ORDER_STATE_INVALID`, `ERR_CLAIM_STATE_INVALID` or `ERR_NFA_STATE_INVALID`, each HTTP 409. Applies to every action endpoint."

        Design: Corner/endpoints/new_sampling_round_is_conditional_on_no_open_change_order
        """
        ctx = fx.project_remediation_active_gross()
        fx.submitted_change_order(ctx, 3.5, 1001)

        response = api.create_soil_sample(
            soil_sample_payload(
                ctx["project"]["id"],
                ctx["work_order"]["id"],
                ctx["laboratory"]["id"],
                sample_point="NORTH_SIDEWALL",
                depth_inches=72,
            ),
            FIELD_TECHNICIAN,
        )
        validate_error(response, ApiErrorId.ERR_PROJECT_STATE_INVALID.value, 409)

        project = fx.read_project(ctx["project"]["id"])
        assert project["status"] == "REMEDIATION_ACTIVE", (
            f"the project never reopened sampling, got {project['status']}"
        )
        assert project["sampling_round"] == 1, (
            f"the round counter did not advance, got {project['sampling_round']}"
        )
        assert project["contamination_class"] == "GROSS", (
            "the first round's classification is untouched, got "
            f"{project['contamination_class']}"
        )

        _, meta = validate_paginated(
            api.list_soil_samples(
                FIELD_TECHNICIAN, params={"tank_project_id": ctx["project"]["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            f"the refused aliquot was never written, got {meta['total_count']}"
        )
