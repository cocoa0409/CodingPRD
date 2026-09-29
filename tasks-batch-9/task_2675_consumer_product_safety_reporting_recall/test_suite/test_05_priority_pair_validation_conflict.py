"""One request breaking two rules at once reports only the more urgent one."""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_field_values,
    assert_unit_ledger_conserved,
)
from test_helpers.test_users import DIRECTOR_HEADERS, OFFICER_HEADERS

# A claim for half again as many units as the recall ever placed in commerce.
OVERSIZED_CLAIM = {
    "consumer_ref": "CR-4001",
    "remedy_type": "REFUND",
    "quantity": 150,
    "unit_price_cents": 4999,
    "shipping_cents_per_unit": 899,
}


class TestRemedyClaimAgainstAnUnapprovedPlan:
    """A claim that is both premature and oversized hears about the plan first."""

    def test_unapproved_plan_is_reported_ahead_of_the_impossible_quantity(self, api):
        """A claim on a still-drafted plan reports the plan's own state, not the units.

        The contract states: "Consumer remedy claims are registered by a
        `ComplianceOfficer` against an `APPROVED` or `MONITORING` recall — any
        other `plan_status` draws `ERR_RECALL_PLAN_STATE_INVALID`." It also
        states: "The `quantity` may not exceed the recall's current
        `units_outstanding`, and a claim promising more units than remain
        uncorrected is refused with `ERR_UNITS_OUTSTANDING_EXCEEDED` (HTTP 422)."
        Because "containment outranks paperwork, and paperwork outranks money",
        the plan's state is the failure the operator hears.

        Design: Difficulty/priority_pair_validation_conflict/remedy_claim_cross_entity_state_priority10_beats_units_fiscal_priority33
        """
        env = fx.draft_recall_env(api)
        recall = fx.get_recall(api, env["recall_id"])
        assert_field_values(
            recall, plan_status="DRAFT", units_in_commerce=100, units_outstanding=100
        )

        response = api.create_remedy_claim(
            f.remedy_claim_payload(env["recall_id"], **OVERSIZED_CLAIM),
            headers=OFFICER_HEADERS,
        )
        validate_error(response, "ERR_RECALL_PLAN_STATE_INVALID", 409)

        after = fx.get_recall(api, env["recall_id"])
        assert_field_values(
            after,
            plan_status="DRAFT",
            units_corrected=0,
            units_outstanding=100,
            effectiveness_flag="PENDING",
        )
        assert_unit_ledger_conserved(after)

        rows, meta = validate_paginated(
            api.list_remedy_claims(
                {"recall_id": env["recall_id"]}, headers=OFFICER_HEADERS
            )
        )
        assert rows == [], f"the refused claim was persisted anyway: {rows}"
        assert meta["total_count"] == 0, meta

    def test_with_the_plan_approved_the_impossible_quantity_becomes_reachable(
        self, api
    ):
        """The very same oversized claim on a monitored plan reports the unit ceiling.

        The contract states: "The `quantity` may not exceed the recall's current
        `units_outstanding`, and a claim promising more units than remain
        uncorrected is refused with `ERR_UNITS_OUTSTANDING_EXCEEDED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/remedy_claim_cross_entity_state_priority10_beats_units_fiscal_priority33
        """
        env = fx.monitoring_recall_env(api)
        recall = fx.get_recall(api, env["recall_id"])
        assert_field_values(
            recall, plan_status="MONITORING", units_outstanding=100
        )

        response = api.create_remedy_claim(
            f.remedy_claim_payload(env["recall_id"], **OVERSIZED_CLAIM),
            headers=OFFICER_HEADERS,
        )
        validate_error(response, "ERR_UNITS_OUTSTANDING_EXCEEDED", 422)

        after = fx.get_recall(api, env["recall_id"])
        assert_field_values(after, units_corrected=0, units_outstanding=100)
        assert_unit_ledger_conserved(after)


class TestRecallClosureGateOrdering:
    """Closure names the shelf before the paperwork and the paperwork before money."""

    def test_unverified_shelf_removal_is_reported_ahead_of_the_missing_paperwork(
        self, api
    ):
        """A monitored recall with product still on a shelf hears the shelf gate.

        The contract states: "Its `notification_status` must be `SATISFIED`, else
        `ERR_NOTIFICATION_NOT_SATISFIED` (HTTP 409) — this is the shelf-removal
        gate, and it deliberately outranks both the paperwork gate and the
        correction-rate gate, because product still sitting on a shelf is the most
        urgent fact about a recall."

        Design: Difficulty/priority_pair_validation_conflict/recall_close_shelf_safety_priority13_beats_paperwork_referential_priority29
        """
        env = fx.monitoring_recall_env(api)
        recall = fx.get_recall(api, env["recall_id"])
        assert_field_values(
            recall,
            plan_status="MONITORING",
            notification_status="IN_PROGRESS",
            units_corrected=0,
            effectiveness_flag="PENDING",
        )
        assert_field_values(
            fx.get_notification(api, env["notification_id"]), status="ISSUED"
        )
        rows, _meta = validate_paginated(
            api.list_progress_reports(
                {"recall_id": env["recall_id"]}, headers=OFFICER_HEADERS
            )
        )
        assert rows == [], f"the recall already carries paperwork: {rows}"

        response = api.close_recall(env["recall_id"], headers=DIRECTOR_HEADERS)
        validate_error(response, "ERR_NOTIFICATION_NOT_SATISFIED", 409)

        after = fx.get_recall(api, env["recall_id"])
        assert_field_values(
            after, plan_status="MONITORING", notification_status="IN_PROGRESS"
        )
        assert_field_values(
            fx.get_notification(api, env["notification_id"]), status="ISSUED"
        )
        model = fx.get_product_model(api, env["model_id"])
        assert_field_values(
            model, open_escalation_count=3, hazard_posture="RESTRICTED"
        )

    def test_with_the_shelf_verified_the_missing_paperwork_becomes_reachable(self, api):
        """Once every shelf is verified, closure reports the unreviewed paperwork.

        The contract states: "At least one progress report on this recall must be
        in `ACCEPTED` status, else `ERR_PROGRESS_REPORT_REQUIRED` (HTTP 422);
        merely filing an effectiveness assessment is not enough, the agency must
        have reviewed it."

        Design: Difficulty/priority_pair_validation_conflict/recall_close_shelf_safety_priority13_beats_paperwork_referential_priority29
        """
        env = fx.satisfied_notification_env(api)
        recall = fx.get_recall(api, env["recall_id"])
        assert_field_values(
            recall,
            plan_status="MONITORING",
            notification_status="SATISFIED",
            effectiveness_flag="PENDING",
        )

        response = api.close_recall(env["recall_id"], headers=DIRECTOR_HEADERS)
        validate_error(response, "ERR_PROGRESS_REPORT_REQUIRED", 422)

        after = fx.get_recall(api, env["recall_id"])
        assert_field_values(after, plan_status="MONITORING")

    def test_with_shelf_and_paperwork_settled_the_correction_rate_is_the_last_gate(
        self, api
    ):
        """With the shelf clear and a reviewed report on file, only money is left.

        The contract states: "And the recall's `effectiveness_flag` must equal
        `MET`, else `ERR_EFFECTIVENESS_NOT_MET` (HTTP 409)." It also states:
        "Acceptance also writes back to the recall: `last_accepted_period_end` is
        set to this report's `period_end`, and when the accepted report's
        `assessment` is `CRITICAL` the recall's `effectiveness_flag` is set to
        `SHORTFALL`."

        Design: Difficulty/priority_pair_validation_conflict/recall_close_shelf_safety_priority13_beats_paperwork_referential_priority29
        """
        env = fx.satisfied_notification_env(api)
        report = fx.accepted_progress_report(
            api,
            env["recall_id"],
            period_start="2026-03-13T00:00:00Z",
            period_end="2026-04-12T00:00:00Z",
            effectiveness_basis="UNITS_BASIS",
        )
        assert_field_values(report, status="ACCEPTED", assessment="CRITICAL")

        recall = fx.get_recall(api, env["recall_id"])
        assert_field_values(
            recall,
            plan_status="MONITORING",
            notification_status="SATISFIED",
            effectiveness_flag="SHORTFALL",
        )

        response = api.close_recall(env["recall_id"], headers=DIRECTOR_HEADERS)
        validate_error(response, "ERR_EFFECTIVENESS_NOT_MET", 409)

        after = fx.get_recall(api, env["recall_id"])
        assert_field_values(after, plan_status="MONITORING")
