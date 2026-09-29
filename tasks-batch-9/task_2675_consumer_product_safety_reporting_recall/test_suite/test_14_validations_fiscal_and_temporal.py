"""Uniqueness keys, closure gates, monthly periods and the fiscal ceilings.

Every refusal here is a boundary: the docket keys that only bite while the
conflicting row is still live, the four closure gates walked one at a time, the
monthly series pinned from both sides, and the three ceilings whose edge is
inclusive.
"""

from datetime import datetime

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_field_values,
    assert_fields_null,
    assert_reserve_conserved,
    assert_unit_ledger_conserved,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    COUNSEL_HEADERS,
    DIRECTOR_HEADERS,
    OFFICER_HEADERS,
)

# The canonical docket freezes an assessment of four alleged violations against
# a report filed two days late behind a hospitalisation: 4,000,000 cents of base
# scaled by 1.25 for the worst injury and by 1.10 for the lateness.
ASSESSED_PENALTY_CENTS = 5500000

# The first monthly period runs from the stop-sale instant for thirty days; the
# second must begin exactly 24 hours after the first one ends.
FIRST_PERIOD_END = "2026-04-12T00:00:00Z"
SECOND_PERIOD_START = "2026-04-13T00:00:00Z"
SECOND_PERIOD_END = "2026-05-13T00:00:00Z"


def _instant(value):
    """The instant a stored ISO 8601 UTC timestamp names."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _assert_same_instant(actual, expected):
    """Compare instants, not renderings.

    The contract fixes the rendering of the four common properties only —
    "`created_at` is an ISO 8601 UTC timestamp with three fractional digits" —
    and asks of a client-supplied timestamp only that it be "a valid ISO 8601
    UTC instant". It never says whether a supplied instant is echoed back byte
    for byte or re-rendered in the canonical form, so the assertion is on the
    instant.
    """
    assert _instant(actual) == _instant(expected), (
        "expected the instant %s, got %s" % (expected, actual)
    )


def _table_offer(api, case_id, amount_cents, offered_by):
    """Table one settlement offer against the case version as it stands now."""
    case = fx.get_penalty_case(api, case_id)
    return fx.make_offer(api, case_id, amount_cents, offered_by, case["version"])


def _verify_the_only_notification(api, env):
    """Acknowledge, audit and verify the recall's single stop-sale notification."""
    fx.acknowledge_notification(api, env["notification_id"], units_on_shelf_reported=0)
    fx.passing_visit(api, env["notification_id"])
    return fx.verify_notification(api, env["notification_id"])


def _accept_first_monthly_report(api, recall_id, **overrides):
    """Open, file and accept one report beginning at the stop-sale instant."""
    recall = fx.get_recall(api, recall_id)
    return fx.accepted_progress_report(
        api,
        recall_id,
        period_start=recall["stop_sale_effective_at"],
        period_end=FIRST_PERIOD_END,
        **overrides,
    )


class TestDocketUniquenessKeys:
    """Five uniqueness keys, three error codes, and the statuses each key sees."""

    def test_a_reused_model_code_is_refused_with_the_registry_specific_code(self, api):
        """The registry key answers with its own code, not the generic conflict.

        The contract states: "The `model_code` is globally unique across all
        product models; a second registration reusing an existing code is
        refused with `ERR_MODEL_CODE_TAKEN`."

        Design: Corner/validations/docket_uniqueness_holds_per_key_and_only_for_non_terminal_rows
        """
        fx.set_clock(api, "2026-03-01T00:00:00Z")
        fx.create_product_model(
            api, model_code="TOAST-X1", units_distributed=100, units_registered=60
        )

        response = api.create_product_model(
            f.product_model_payload(
                model_code="TOAST-X1",
                brand="Other Brand",
                units_distributed=5,
                units_registered=1,
            ),
            headers=ADMIN_HEADERS,
        )

        validate_error(response, "ERR_MODEL_CODE_TAKEN", 409)

    def test_a_second_report_on_an_evaluation_holding_a_draft_is_a_duplicate(self, api):
        """One report per evaluation while the first is still in DRAFT.

        The contract states: "One report per evaluation: a second report against
        an evaluation that already has one in `DRAFT`, `SUBMITTED` or `ACCEPTED`
        is refused with `ERR_DUPLICATE_DOCKET_ENTRY`."

        Design: Corner/validations/docket_uniqueness_holds_per_key_and_only_for_non_terminal_rows
        """
        env = fx.draft_report_env(api)
        assert_field_values(env["report"], status="DRAFT")

        response = api.create_section_report(
            f.section_report_payload(
                env["evaluation_id"],
                corrective_action_type="REPAIR",
                corrective_action_summary="Second filing attempt on the same evaluation.",
            ),
            headers=OFFICER_HEADERS,
        )

        validate_error(response, "ERR_DUPLICATE_DOCKET_ENTRY", 409)

    def test_a_second_report_is_allowed_once_the_first_was_returned_for_info(self, api):
        """RETURNED_FOR_INFO is outside the guarded set, so a fresh draft is legal.

        The contract states: "One report per evaluation: a second report against
        an evaluation that already has one in `DRAFT`, `SUBMITTED` or `ACCEPTED`
        is refused with `ERR_DUPLICATE_DOCKET_ENTRY`." A `decision` of
        `RETURNED_FOR_INFO` "advances it `SUBMITTED → RETURNED_FOR_INFO`", which
        is none of those three.

        Design: Corner/validations/docket_uniqueness_holds_per_key_and_only_for_non_terminal_rows
        """
        env = fx.submitted_report_env(api)
        returned = fx.review_section_report(
            api, env["report_id"], "RETURNED_FOR_INFO", note="Need the weld report."
        )
        assert_field_values(returned, status="RETURNED_FOR_INFO")

        second = fx.create_section_report(
            api,
            env["evaluation_id"],
            corrective_action_type="REPAIR",
            corrective_action_summary="Replacement filing while the first is returned.",
        )

        assert_field_values(second, status="DRAFT", corrective_action_type="REPAIR")
        assert second["id"] != env["report_id"]

    def test_a_second_recall_on_the_same_accepted_report_is_a_duplicate(self, api):
        """One recall per report, and the collection still shows a single row.

        The contract states: "The referenced report must be in `status`
        `ACCEPTED`, otherwise `ERR_SECTION_REPORT_STATE_INVALID`; and one recall
        per report, so a second recall on the same `section_report_id` is
        refused with `ERR_DUPLICATE_DOCKET_ENTRY`."

        Design: Corner/validations/docket_uniqueness_holds_per_key_and_only_for_non_terminal_rows
        """
        env = fx.draft_recall_env(api)

        response = api.create_recall(
            f.recall_payload(
                env["report_id"],
                remedy_options=["REFUND"],
                units_in_commerce=50,
                participation_goal_pct=20.00,
                correction_deadline_at="2026-10-31T00:00:00Z",
            ),
            headers=OFFICER_HEADERS,
        )

        validate_error(response, "ERR_DUPLICATE_DOCKET_ENTRY", 409)

        rows, meta = validate_paginated(
            api.list_recalls(
                {"section_report_id": env["report_id"]}, headers=OFFICER_HEADERS
            )
        )
        assert meta["total_count"] == 1, meta
        assert [row["id"] for row in rows] == [env["recall_id"]]

    def test_a_second_penalty_case_on_the_same_report_is_a_duplicate(self, api):
        """The penalty docket admits one case per statutory report.

        The contract states: "At most one case may exist per
        `section_report_id`; a second attempt is refused with
        `ERR_DUPLICATE_DOCKET_ENTRY`."

        Design: Corner/validations/docket_uniqueness_holds_per_key_and_only_for_non_terminal_rows
        """
        env = fx.penalty_case_on_report_env(api)

        response = api.create_penalty_case(
            f.penalty_case_payload(env["report_id"], violation_count=2),
            headers=COUNSEL_HEADERS,
        )

        validate_error(response, "ERR_DUPLICATE_DOCKET_ENTRY", 409)
        assert_field_values(
            fx.get_penalty_case(api, env["case_id"]), status="ASSESSMENT_OPEN"
        )

    def test_a_repeat_enrollment_of_one_retailer_uses_the_retailer_specific_code(
        self, api
    ):
        """The (recall, retailer) key answers with its own code, not the generic one.

        The contract states: "At most one notification may exist per pairing of
        `recall_id` and `retailer_id`; a second is refused with
        `ERR_DUPLICATE_RETAILER_NOTIFICATION` (HTTP 409)."

        Design: Corner/validations/docket_uniqueness_holds_per_key_and_only_for_non_terminal_rows
        """
        env = fx.draft_recall_env(api)

        response = api.create_retailer_notification(
            f.retailer_notification_payload(env["recall_id"], env["retailer_id"]),
            headers=OFFICER_HEADERS,
        )

        validate_error(response, "ERR_DUPLICATE_RETAILER_NOTIFICATION", 409)

        rows, meta = validate_paginated(
            fx.list_notifications(api, recall_id=env["recall_id"])
        )
        assert meta["total_count"] == 1, meta
        assert [row["id"] for row in rows] == [env["notification_id"]]

    def test_a_second_evaluation_is_refused_while_the_first_is_reportable(self, api):
        """The live-evaluation key covers the REPORTABLE outcome as well.

        The contract states: "Only one live evaluation may exist per pattern: if
        another evaluation on the same `hazard_pattern_id` is currently `OPEN`,
        `IN_REVIEW` or `REPORTABLE`, the request is refused with
        `ERR_DUPLICATE_DOCKET_ENTRY`."

        Design: Corner/validations/docket_uniqueness_holds_per_key_and_only_for_non_terminal_rows
        """
        env = fx.determined_evaluation_env(api)
        assert_field_values(env["evaluation"], status="REPORTABLE")

        response = api.create_evaluation(
            f.evaluation_payload(
                env["pattern_id"], standard_basis="UNREASONABLE_RISK"
            ),
            headers=OFFICER_HEADERS,
        )

        validate_error(response, "ERR_DUPLICATE_DOCKET_ENTRY", 409)

    def test_a_second_evaluation_is_allowed_once_the_first_is_not_reportable(self, api):
        """A NOT_REPORTABLE outcome falls outside the key, so the pattern reopens.

        The contract states: "Only one live evaluation may exist per pattern: if
        another evaluation on the same `hazard_pattern_id` is currently `OPEN`,
        `IN_REVIEW` or `REPORTABLE`, the request is refused with
        `ERR_DUPLICATE_DOCKET_ENTRY`." The evaluation `status` "moves through
        `OPEN`, `IN_REVIEW` and then one of the two terminal outcomes
        `REPORTABLE` or `NOT_REPORTABLE`", and only the first of those two is
        named by the key.

        Design: Corner/validations/docket_uniqueness_holds_per_key_and_only_for_non_terminal_rows
        """
        env = fx.evaluation_env(api)
        fx.begin_review(api, env["evaluation_id"])
        closed = fx.determine_evaluation(
            api,
            env["evaluation_id"],
            determination="NOT_REPORTABLE",
            defect_score=2,
            risk_score=1,
            determination_note="Isolated misuse; the defect standard is not met.",
        )
        assert_field_values(closed, status="NOT_REPORTABLE")

        second = fx.create_evaluation(
            api, env["pattern_id"], standard_basis="UNREASONABLE_RISK"
        )

        assert_field_values(
            second, status="OPEN", standard_basis="UNREASONABLE_RISK"
        )
        assert second["id"] != env["evaluation_id"]


class TestFiscalAndUnitCeilings:
    """The two lowest-priority guards, both of them inclusive ceilings."""

    def test_a_claim_for_more_units_than_remain_outstanding_is_refused(self, api):
        """One unit past the outstanding ledger is an impossible promise.

        The contract states: "The `quantity` may not exceed the recall's current
        `units_outstanding`, and a claim promising more units than remain
        uncorrected is refused with `ERR_UNITS_OUTSTANDING_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/fiscal_ceilings_reject_impossible_quantities_and_over_assessment_offers
        """
        env = fx.monitoring_recall_env(api)
        assert_field_values(env["recall"], units_in_commerce=100, units_outstanding=100)

        response = api.create_remedy_claim(
            f.remedy_claim_payload(
                env["recall_id"],
                consumer_ref="C-900",
                remedy_type="REFUND",
                quantity=101,
                unit_price_cents=8999,
                shipping_cents_per_unit=700,
            ),
            headers=OFFICER_HEADERS,
        )

        validate_error(response, "ERR_UNITS_OUTSTANDING_EXCEEDED", 422)

        recall = fx.get_recall(api, env["recall_id"])
        assert_field_values(recall, units_corrected=0, units_outstanding=100)
        assert_unit_ledger_conserved(recall)

    def test_a_claim_for_exactly_the_outstanding_units_is_accepted(self, api):
        """The unit ceiling is inclusive and registration moves no units.

        The contract states: "The `quantity` may not exceed the recall's current
        `units_outstanding`, and a claim promising more units than remain
        uncorrected is refused with `ERR_UNITS_OUTSTANDING_EXCEEDED` (HTTP 422)."
        It also states: "Registration deliberately moves no units: neither
        `units_corrected` nor `units_outstanding` changes until fulfilment."

        Design: Corner/validations/fiscal_ceilings_reject_impossible_quantities_and_over_assessment_offers
        """
        env = fx.monitoring_recall_env(api)

        claim = fx.create_claim(
            api,
            env["recall_id"],
            consumer_ref="C-901",
            remedy_type="REFUND",
            quantity=100,
            unit_price_cents=8999,
            shipping_cents_per_unit=700,
        )

        assert_field_values(claim, quantity=100, status="SUBMITTED")

        recall = fx.get_recall(api, env["recall_id"])
        assert_field_values(recall, units_corrected=0, units_outstanding=100)
        assert_unit_ledger_conserved(recall)

    def test_approval_rechecks_the_quantity_against_the_ledger_of_the_moment(self, api):
        """A claim that fitted at registration is refused once the ledger moves.

        The contract states: "It re-checks the quantity against the recall's
        `units_outstanding` as it stands at approval time, because other claims
        may have been fulfilled in the meantime, and a claim that no longer fits
        is refused with `ERR_UNITS_OUTSTANDING_EXCEEDED`."

        Design: Corner/validations/fiscal_ceilings_reject_impossible_quantities_and_over_assessment_offers
        """
        env = fx.monitoring_recall_env(api)
        pending = fx.create_claim(
            api,
            env["recall_id"],
            consumer_ref="C-910",
            remedy_type="REFUND",
            quantity=60,
            unit_price_cents=8999,
            shipping_cents_per_unit=700,
        )

        fx.fulfilled_claim(
            api,
            env["recall_id"],
            consumer_ref="C-911",
            remedy_type="REFUND",
            quantity=50,
            unit_price_cents=8999,
            shipping_cents_per_unit=700,
        )
        recall = fx.get_recall(api, env["recall_id"])
        assert_field_values(recall, units_corrected=50, units_outstanding=50)

        response = api.approve_claim(pending["id"], headers=OFFICER_HEADERS)

        validate_error(response, "ERR_UNITS_OUTSTANDING_EXCEEDED", 422)
        assert_field_values(fx.get_claim(api, pending["id"]), status="SUBMITTED")

    def test_an_offer_above_the_frozen_assessment_is_refused(self, api):
        """A figure over the frozen assessment consumes neither round nor reserve.

        The contract states: "Finally, `amount_cents` may not exceed
        `assessed_penalty_cents`, with equality allowed so that a full-value
        agency offer is legal, and a larger figure is refused with
        `ERR_OFFER_EXCEEDS_ASSESSMENT` (HTTP 422)."

        Design: Corner/validations/fiscal_ceilings_reject_impossible_quantities_and_over_assessment_offers
        """
        env = fx.penalty_case_on_report_env(api, violation_count=4)
        case = env["case"]
        assert_field_values(case, assessed_penalty_cents=ASSESSED_PENALTY_CENTS)

        response = api.create_offer(
            env["case_id"],
            f.offer_payload(6000000, "AGENCY", case["version"]),
            headers=COUNSEL_HEADERS,
        )

        validate_error(response, "ERR_OFFER_EXCEEDS_ASSESSMENT", 422)

        after = fx.get_penalty_case(api, env["case_id"])
        assert_field_values(
            after,
            status="ASSESSMENT_OPEN",
            current_offer_round=0,
            reserved_cents=0,
            available_cents=ASSESSED_PENALTY_CENTS,
        )
        assert_fields_null(after, "current_offer_cents", "current_offer_by")
        assert_reserve_conserved(after)

    def test_an_offer_equal_to_the_frozen_assessment_is_accepted(self, api):
        """A full-value agency offer is legal and reserves the whole assessment.

        The contract states: "Finally, `amount_cents` may not exceed
        `assessed_penalty_cents`, with equality allowed so that a full-value
        agency offer is legal, and a larger figure is refused with
        `ERR_OFFER_EXCEEDS_ASSESSMENT` (HTTP 422)." It also states: "An `AGENCY`
        offer commits the money the office is prepared to settle for:
        `reserved_cents` becomes `amount_cents` and `available_cents` becomes
        `assessed_penalty_cents` minus `amount_cents`."

        Design: Corner/validations/fiscal_ceilings_reject_impossible_quantities_and_over_assessment_offers
        """
        env = fx.penalty_case_on_report_env(api, violation_count=4)

        offered = _table_offer(api, env["case_id"], ASSESSED_PENALTY_CENTS, "AGENCY")

        assert_field_values(
            offered,
            status="OFFER_MADE",
            current_offer_round=1,
            current_offer_cents=ASSESSED_PENALTY_CENTS,
            current_offer_by="AGENCY",
            reserved_cents=ASSESSED_PENALTY_CENTS,
            available_cents=0,
        )
        assert_reserve_conserved(offered)


class TestRecallClosureGatesFireOneAtATime:
    """Each closure gate is provoked alone, in the order the contract declares."""

    def test_closure_needs_the_plan_in_monitoring_even_when_everything_else_is_done(
        self, api
    ):
        """An APPROVED plan is refused on its own state before any other gate.

        The contract states: "Closing a recall advances `plan_status`
        `MONITORING → CLOSED` and is gated by four independent conditions which
        are evaluated in a fixed order, so the operator always hears the most
        urgent unresolved fact first. The recall must be in `MONITORING`, else
        `ERR_RECALL_PLAN_STATE_INVALID`."

        Design: Corner/validations/each_recall_close_gate_fires_alone_in_declared_priority_order
        """
        env = fx.approved_recall_env(api)
        _verify_the_only_notification(api, env)
        fx.fulfilled_claim(
            api,
            env["recall_id"],
            consumer_ref="C-300",
            remedy_type="REFUND",
            quantity=30,
            unit_price_cents=8999,
            shipping_cents_per_unit=700,
        )
        accepted = _accept_first_monthly_report(api, env["recall_id"])
        assert_field_values(accepted, status="ACCEPTED", assessment="ON_TRACK")

        before = fx.get_recall(api, env["recall_id"])
        assert_field_values(
            before,
            plan_status="APPROVED",
            notification_status="SATISFIED",
            effectiveness_flag="MET",
        )

        response = api.close_recall(env["recall_id"], headers=DIRECTOR_HEADERS)

        validate_error(response, "ERR_RECALL_PLAN_STATE_INVALID", 409)
        assert_field_values(fx.get_recall(api, env["recall_id"]), plan_status="APPROVED")

    def test_closure_reports_the_shelf_removal_gate_when_only_it_is_unmet(self, api):
        """An unverified stop-sale blocks closure even with the paperwork done.

        The contract states: "Its `notification_status` must be `SATISFIED`, else
        `ERR_NOTIFICATION_NOT_SATISFIED` (HTTP 409) — this is the shelf-removal
        gate, and it deliberately outranks both the paperwork gate and the
        correction-rate gate, because product still sitting on a shelf is the
        most urgent fact about a recall."

        Design: Corner/validations/each_recall_close_gate_fires_alone_in_declared_priority_order
        """
        env = fx.monitoring_recall_env(api)
        fx.fulfilled_claim(
            api,
            env["recall_id"],
            consumer_ref="C-301",
            remedy_type="REFUND",
            quantity=30,
            unit_price_cents=8999,
            shipping_cents_per_unit=700,
        )
        accepted = _accept_first_monthly_report(api, env["recall_id"])
        assert_field_values(accepted, status="ACCEPTED", assessment="ON_TRACK")

        before = fx.get_recall(api, env["recall_id"])
        assert_field_values(
            before,
            plan_status="MONITORING",
            notification_status="IN_PROGRESS",
            effectiveness_flag="MET",
        )

        response = api.close_recall(env["recall_id"], headers=DIRECTOR_HEADERS)

        validate_error(response, "ERR_NOTIFICATION_NOT_SATISFIED", 409)
        assert_field_values(
            fx.get_recall(api, env["recall_id"]), plan_status="MONITORING"
        )

    def test_closure_reports_the_paperwork_gate_once_the_shelf_gate_is_cleared(
        self, api
    ):
        """With shelves verified and the rate met, the missing report is next.

        The contract states: "At least one progress report on this recall must be
        in `ACCEPTED` status, else `ERR_PROGRESS_REPORT_REQUIRED` (HTTP 422);
        merely filing an effectiveness assessment is not enough, the agency must
        have reviewed it."

        Design: Corner/validations/each_recall_close_gate_fires_alone_in_declared_priority_order
        """
        env = fx.satisfied_notification_env(api)
        fx.fulfilled_claim(
            api,
            env["recall_id"],
            consumer_ref="C-302",
            remedy_type="REFUND",
            quantity=30,
            unit_price_cents=8999,
            shipping_cents_per_unit=700,
        )

        before = fx.get_recall(api, env["recall_id"])
        assert_field_values(
            before,
            plan_status="MONITORING",
            notification_status="SATISFIED",
            effectiveness_flag="MET",
        )

        response = api.close_recall(env["recall_id"], headers=DIRECTOR_HEADERS)

        validate_error(response, "ERR_PROGRESS_REPORT_REQUIRED", 422)
        assert_field_values(
            fx.get_recall(api, env["recall_id"]), plan_status="MONITORING"
        )

    def test_closure_reports_the_correction_rate_gate_last(self, api):
        """With shelves verified and a report accepted, only the rate remains.

        The contract states: "And the recall's `effectiveness_flag` must equal
        `MET`, else `ERR_EFFECTIVENESS_NOT_MET` (HTTP 409)." Acceptance itself
        writes back: "when the accepted report's `assessment` is `CRITICAL` the
        recall's `effectiveness_flag` is set to `SHORTFALL`."

        Design: Corner/validations/each_recall_close_gate_fires_alone_in_declared_priority_order
        """
        env = fx.satisfied_notification_env(api)
        accepted = _accept_first_monthly_report(api, env["recall_id"])
        assert_field_values(accepted, status="ACCEPTED", assessment="CRITICAL")
        assert_decimal_equals(accepted["effectiveness_rate"], "0.00")

        before = fx.get_recall(api, env["recall_id"])
        assert_field_values(
            before,
            plan_status="MONITORING",
            notification_status="SATISFIED",
            effectiveness_flag="SHORTFALL",
        )

        response = api.close_recall(env["recall_id"], headers=DIRECTOR_HEADERS)

        validate_error(response, "ERR_EFFECTIVENESS_NOT_MET", 409)
        assert_field_values(
            fx.get_recall(api, env["recall_id"]), plan_status="MONITORING"
        )

    def test_closure_succeeds_once_all_four_gates_are_satisfied(self, api):
        """The fourth attempt closes the recall and relaxes the model's posture.

        The contract states: "On success, closure relaxes the containment gate on
        the product model reached from the recall through its `section_report_id`
        and that report's `reportability_evaluation_id`: when this recall was
        that model's last open escalation source, the model's
        `open_escalation_count` is set back to 0 and its `hazard_posture` back to
        `MONITORED`."

        Design: Corner/validations/each_recall_close_gate_fires_alone_in_declared_priority_order
        """
        env = fx.satisfied_notification_env(api)
        fx.fulfilled_claim(
            api,
            env["recall_id"],
            consumer_ref="C-303",
            remedy_type="REFUND",
            quantity=30,
            unit_price_cents=8999,
            shipping_cents_per_unit=700,
        )
        accepted = _accept_first_monthly_report(api, env["recall_id"])
        assert_field_values(accepted, assessment="ON_TRACK")
        assert_decimal_equals(accepted["effectiveness_rate"], "30.00")

        closed = fx.close_recall(api, env["recall_id"])

        assert_field_values(
            closed,
            plan_status="CLOSED",
            notification_status="SATISFIED",
            effectiveness_flag="MET",
            units_corrected=30,
            units_outstanding=70,
        )
        assert_unit_ledger_conserved(closed)
        assert_field_values(
            fx.get_product_model(api, env["model_id"]),
            open_escalation_count=0,
            hazard_posture="MONITORED",
        )


class TestProgressReportPeriodSeries:
    """The monthly series is pinned from both sides on the same recall."""

    def test_the_first_period_must_begin_at_the_stop_sale_instant(self, api):
        """With no prior filing the series may only start where the stop-sale did.

        The contract states: "Second, periods may not skip time: taking the
        latest `period_end` across that same comparison set, the new
        `period_start` must equal that latest `period_end` plus exactly 24 hours;
        and when no such prior report exists, the new `period_start` must equal
        the recall's `stop_sale_effective_at` exactly, so that the very first
        monthly period begins the instant the stop-sale took effect."

        Design: Corner/validations/progress_report_periods_must_be_contiguous_and_non_overlapping
        """
        env = fx.monitoring_recall_env(api)
        stop_sale_at = fx.get_recall(api, env["recall_id"])["stop_sale_effective_at"]

        response = api.create_progress_report(
            f.progress_report_payload(
                env["recall_id"],
                period_start="2026-03-14T00:00:00Z",
                period_end="2026-04-13T00:00:00Z",
            ),
            headers=OFFICER_HEADERS,
        )

        validate_error(response, "ERR_REPORT_PERIOD_GAP", 422)

        first = fx.create_progress_report(
            api,
            env["recall_id"],
            period_start=stop_sale_at,
            period_end=FIRST_PERIOD_END,
        )
        assert_field_values(first, status="DRAFT")
        _assert_same_instant(first["period_end"], FIRST_PERIOD_END)
        _assert_same_instant(first["period_start"], stop_sale_at)

    def test_a_period_starting_at_the_previous_period_end_overlaps(self, api):
        """Closed intervals mean that merely touching the prior period conflicts.

        The contract states: "First, periods may not overlap: because both
        endpoints are inclusive, the new period conflicts with an existing one
        when the new `period_start` is at or before the existing `period_end` and
        the existing `period_start` is at or before the new `period_end`, and a
        conflict is refused with `ERR_REPORT_PERIOD_OVERLAP` (HTTP 409)." The
        contrast is deliberate: "a new reporting period beginning at exactly the
        previous `period_end` *does* overlap, whereas an audit window beginning
        at the previous `window_end` does not."

        Design: Corner/validations/progress_report_periods_must_be_contiguous_and_non_overlapping
        """
        env = fx.monitoring_recall_env(api)
        stop_sale_at = fx.get_recall(api, env["recall_id"])["stop_sale_effective_at"]
        filed = fx.submitted_progress_report(
            api,
            env["recall_id"],
            period_start=stop_sale_at,
            period_end=FIRST_PERIOD_END,
        )
        assert_field_values(filed, status="SUBMITTED")

        response = api.create_progress_report(
            f.progress_report_payload(
                env["recall_id"],
                period_start=FIRST_PERIOD_END,
                period_end="2026-05-12T00:00:00Z",
            ),
            headers=OFFICER_HEADERS,
        )

        validate_error(response, "ERR_REPORT_PERIOD_OVERLAP", 409)

    def test_a_later_period_must_begin_exactly_24_hours_after_the_last_one(self, api):
        """One day too late is a gap; the exact instant is accepted.

        The contract states: "Second, periods may not skip time: taking the
        latest `period_end` across that same comparison set, the new
        `period_start` must equal that latest `period_end` plus exactly 24
        hours." Any other start "is a reporting gap and is refused with
        `ERR_REPORT_PERIOD_GAP` (HTTP 422)."

        Design: Corner/validations/progress_report_periods_must_be_contiguous_and_non_overlapping
        """
        env = fx.monitoring_recall_env(api)
        stop_sale_at = fx.get_recall(api, env["recall_id"])["stop_sale_effective_at"]
        fx.submitted_progress_report(
            api,
            env["recall_id"],
            period_start=stop_sale_at,
            period_end=FIRST_PERIOD_END,
        )

        response = api.create_progress_report(
            f.progress_report_payload(
                env["recall_id"],
                period_start="2026-04-14T00:00:00Z",
                period_end="2026-05-14T00:00:00Z",
            ),
            headers=OFFICER_HEADERS,
        )

        validate_error(response, "ERR_REPORT_PERIOD_GAP", 422)

        second = fx.create_progress_report(
            api,
            env["recall_id"],
            period_start=SECOND_PERIOD_START,
            period_end=SECOND_PERIOD_END,
        )
        assert_field_values(second, status="DRAFT")
        _assert_same_instant(second["period_start"], SECOND_PERIOD_START)

        _rows, meta = validate_paginated(
            api.list_progress_reports(
                {"recall_id": env["recall_id"]}, headers=OFFICER_HEADERS
            )
        )
        assert meta["total_count"] == 2, meta

    def test_an_abandoned_draft_blocks_neither_temporal_check(self, api):
        """A DRAFT period is outside the comparison set both rules read.

        The contract states: "Two temporal rules keep the monthly series honest,
        and they are checked in this order against the comparison set of progress
        reports on the *same* recall whose `status` is `SUBMITTED` or `ACCEPTED` —
        `DRAFT` reports are excluded from both, so an abandoned draft never blocks
        a real filing."

        Design: Corner/validations/progress_report_periods_must_be_contiguous_and_non_overlapping
        """
        env = fx.monitoring_recall_env(api)
        stop_sale_at = fx.get_recall(api, env["recall_id"])["stop_sale_effective_at"]
        abandoned = fx.create_progress_report(
            api,
            env["recall_id"],
            period_start=stop_sale_at,
            period_end=FIRST_PERIOD_END,
        )
        assert_field_values(abandoned, status="DRAFT")

        replacement = fx.create_progress_report(
            api,
            env["recall_id"],
            period_start=stop_sale_at,
            period_end=FIRST_PERIOD_END,
        )

        assert_field_values(replacement, status="DRAFT")
        _assert_same_instant(replacement["period_end"], FIRST_PERIOD_END)
        assert replacement["id"] != abandoned["id"]

        filed = fx.submit_progress_report(api, replacement["id"])
        assert_field_values(filed, status="SUBMITTED")


class TestDeterminationScoreSupport:
    """The score-support test is basis-scoped and mirrored in both directions."""

    def _in_review(self, api, standard_basis):
        """A confirmed pattern with its evaluation carried to IN_REVIEW."""
        env = fx.evaluation_env(api, standard_basis=standard_basis)
        fx.begin_review(api, env["evaluation_id"])
        return env

    def test_a_reportable_call_under_the_defect_basis_needs_five_defect_points(
        self, api
    ):
        """A high risk score cannot rescue a defect-basis reportable filing.

        The contract states: "For a `determination` of `REPORTABLE`: under
        `DEFECT` the `defect_score` must be at least 5; under
        `UNREASONABLE_RISK` the `risk_score` must be at least 5; under
        `NONCOMPLIANCE` or `VOLUNTARY_STANDARD_FAILURE` the sum of
        `defect_score` and `risk_score` must be at least 8." Failure is refused
        with `ERR_DETERMINATION_UNSUPPORTED` (HTTP 422).

        Design: Corner/validations/determination_must_be_supported_by_the_scores_in_both_directions
        """
        env = self._in_review(api, "DEFECT")

        response = api.determine_evaluation(
            env["evaluation_id"],
            f.determination_payload(
                determination="REPORTABLE",
                defect_score=4,
                risk_score=9,
                determination_note="High risk score offered as the basis.",
            ),
            headers=OFFICER_HEADERS,
        )

        validate_error(response, "ERR_DETERMINATION_UNSUPPORTED", 422)

        held = fx.get_evaluation(api, env["evaluation_id"])
        assert_field_values(held, status="IN_REVIEW")
        assert_fields_null(held, "determined_at", "report_due_at")

        decided = fx.determine_evaluation(
            api,
            env["evaluation_id"],
            determination="REPORTABLE",
            defect_score=5,
            risk_score=2,
            determination_note="Defect score exactly at the reporting standard.",
        )

        assert_field_values(decided, status="REPORTABLE", defect_score=5, risk_score=2)
        assert decided["report_due_at"].startswith("2026-03-11T00:00:00"), (
            f"report_due_at is not determined_at plus 240 hours: "
            f"{decided['report_due_at']}"
        )
        assert_field_values(
            fx.get_product_model(api, env["model_id"]), hazard_posture="FROZEN"
        )

    def test_a_not_reportable_call_under_the_defect_basis_needs_fewer_than_five(
        self, api
    ):
        """The mirror is strict: qualifying evidence forbids a no-action filing.

        The contract states: "For a `determination` of `NOT_REPORTABLE` the same
        three tests must fail strictly: under `DEFECT` the `defect_score` must be
        below 5; under `UNREASONABLE_RISK` the `risk_score` must be below 5;
        under `NONCOMPLIANCE` or `VOLUNTARY_STANDARD_FAILURE` the sum of
        `defect_score` and `risk_score` must be below 8." And: "An analyst
        therefore cannot file a no-action determination on evidence that meets
        the reporting standard, nor a reportable determination on evidence that
        does not."

        Design: Corner/validations/determination_must_be_supported_by_the_scores_in_both_directions
        """
        env = self._in_review(api, "DEFECT")

        response = api.determine_evaluation(
            env["evaluation_id"],
            f.determination_payload(
                determination="NOT_REPORTABLE",
                defect_score=7,
                risk_score=1,
                determination_note="No action proposed despite a qualifying defect score.",
            ),
            headers=OFFICER_HEADERS,
        )

        validate_error(response, "ERR_DETERMINATION_UNSUPPORTED", 422)
        assert_field_values(
            fx.get_evaluation(api, env["evaluation_id"]), status="IN_REVIEW"
        )

        decided = fx.determine_evaluation(
            api,
            env["evaluation_id"],
            determination="NOT_REPORTABLE",
            defect_score=4,
            risk_score=1,
            determination_note="Defect score one point below the reporting standard.",
        )

        assert_field_values(decided, status="NOT_REPORTABLE", defect_score=4)
        assert_fields_null(decided, "report_due_at")
        assert_field_values(
            fx.get_product_model(api, env["model_id"]), hazard_posture="MONITORED"
        )

    def test_the_unreasonable_risk_basis_reads_only_the_risk_score(self, api):
        """A perfect defect score cannot carry a risk-basis reportable filing.

        The contract states: "Both branches are then guarded by a **score-support
        test** keyed on the evaluation's own `standard_basis`, and the two
        branches are exact mirror images of each other. For a `determination` of
        `REPORTABLE`: under `DEFECT` the `defect_score` must be at least 5; under
        `UNREASONABLE_RISK` the `risk_score` must be at least 5."

        Design: Corner/validations/determination_must_be_supported_by_the_scores_in_both_directions
        """
        env = self._in_review(api, "UNREASONABLE_RISK")

        response = api.determine_evaluation(
            env["evaluation_id"],
            f.determination_payload(
                determination="REPORTABLE",
                defect_score=10,
                risk_score=4,
                determination_note="Defect score offered where the risk standard applies.",
            ),
            headers=OFFICER_HEADERS,
        )

        validate_error(response, "ERR_DETERMINATION_UNSUPPORTED", 422)

        decided = fx.determine_evaluation(
            api,
            env["evaluation_id"],
            determination="REPORTABLE",
            defect_score=2,
            risk_score=5,
            determination_note="Risk score exactly at the unreasonable-risk standard.",
        )

        assert_field_values(decided, status="REPORTABLE", defect_score=2, risk_score=5)

    def test_a_summed_basis_needs_eight_points_for_a_reportable_call(self, api):
        """Under NONCOMPLIANCE the two scores are added before the comparison.

        The contract states: "under `NONCOMPLIANCE` or
        `VOLUNTARY_STANDARD_FAILURE` the sum of `defect_score` and `risk_score`
        must be at least 8."

        Design: Corner/validations/determination_must_be_supported_by_the_scores_in_both_directions
        """
        env = self._in_review(api, "NONCOMPLIANCE")

        response = api.determine_evaluation(
            env["evaluation_id"],
            f.determination_payload(
                determination="REPORTABLE",
                defect_score=4,
                risk_score=3,
                determination_note="Seven combined points offered against the standard.",
            ),
            headers=OFFICER_HEADERS,
        )

        validate_error(response, "ERR_DETERMINATION_UNSUPPORTED", 422)

        decided = fx.determine_evaluation(
            api,
            env["evaluation_id"],
            determination="REPORTABLE",
            defect_score=4,
            risk_score=4,
            determination_note="Eight combined points, exactly at the standard.",
        )

        assert_field_values(decided, status="REPORTABLE", defect_score=4, risk_score=4)

    def test_a_summed_basis_needs_under_eight_points_for_a_not_reportable_call(
        self, api
    ):
        """Under VOLUNTARY_STANDARD_FAILURE the summed mirror is strict too.

        The contract states: "under `NONCOMPLIANCE` or
        `VOLUNTARY_STANDARD_FAILURE` the sum of `defect_score` and `risk_score`
        must be below 8." Either failure "is refused with
        `ERR_DETERMINATION_UNSUPPORTED` (HTTP 422)".

        Design: Corner/validations/determination_must_be_supported_by_the_scores_in_both_directions
        """
        env = self._in_review(api, "VOLUNTARY_STANDARD_FAILURE")

        response = api.determine_evaluation(
            env["evaluation_id"],
            f.determination_payload(
                determination="NOT_REPORTABLE",
                defect_score=4,
                risk_score=4,
                determination_note="No action proposed on eight combined points.",
            ),
            headers=OFFICER_HEADERS,
        )

        validate_error(response, "ERR_DETERMINATION_UNSUPPORTED", 422)

        decided = fx.determine_evaluation(
            api,
            env["evaluation_id"],
            determination="NOT_REPORTABLE",
            defect_score=4,
            risk_score=3,
            determination_note="Seven combined points, one below the standard.",
        )

        assert_field_values(
            decided, status="NOT_REPORTABLE", defect_score=4, risk_score=3
        )


class TestRegistrationCardReachCeiling:
    """The registry ceiling binds one channel and leaves the other three free."""

    def test_a_registration_card_reaching_past_the_registry_is_refused(self, api):
        """Sixty-one cards against sixty registered owners is one too many.

        The contract states: "A `REGISTRATION_CARD` notice can only reach owners
        the firm actually has on file, so its `reach_count` may not exceed the
        `units_registered` of the product model behind the recall — a model
        reached by following the recall's `section_report_id` to the report, that
        report's `reportability_evaluation_id` to the evaluation, and the
        evaluation's `product_model_id` to the model." Exceeding it "is refused
        with `ERR_REACH_EXCEEDS_REGISTRY` (HTTP 422)".

        Design: Corner/validations/registration_card_reach_is_capped_by_the_registry_but_other_channels_are_not
        """
        env = fx.draft_recall_env(api)

        assert_field_values(
            fx.get_product_model(api, env["model_id"]), units_registered=60
        )

        response = api.create_consumer_notice(
            f.consumer_notice_payload(
                env["recall_id"], channel="REGISTRATION_CARD", reach_count=61
            ),
            headers=OFFICER_HEADERS,
        )

        validate_error(response, "ERR_REACH_EXCEEDS_REGISTRY", 422)

        notices, meta = validate_paginated(
            api.list_consumer_notices(
                {"recall_id": env["recall_id"]}, headers=OFFICER_HEADERS
            )
        )
        assert meta["total_count"] == 1, (
            f"the refused card must not have been filed: {meta['total_count']} "
            f"notices stand on the recall"
        )
        assert_field_values(notices[0], channel="DIRECT_NOTICE")

    def test_a_registration_card_reaching_exactly_the_registry_is_scheduled(self, api):
        """Sixty cards against sixty registered owners sits on the edge and passes.

        The contract states: "its `reach_count` may not exceed the
        `units_registered` of the product model behind the recall". And: "Each
        notice is created in `status` `SCHEDULED` with `released_at` null."

        Design: Corner/validations/registration_card_reach_is_capped_by_the_registry_but_other_channels_are_not
        """
        env = fx.draft_recall_env(api)

        notice = fx.create_notice(
            api, env["recall_id"], channel="REGISTRATION_CARD", reach_count=60
        )

        assert_field_values(
            notice,
            channel="REGISTRATION_CARD",
            reach_count=60,
            status="SCHEDULED",
        )
        assert_fields_null(notice, "released_at")

    def test_the_other_three_channels_carry_no_registry_ceiling_at_all(self, api):
        """A press release, a web posting and a direct notice may each dwarf the registry.

        The contract states: "The `DIRECT_NOTICE`, `PRESS_RELEASE` and
        `WEB_POSTING` channels have no registry ceiling at all."

        Design: Corner/validations/registration_card_reach_is_capped_by_the_registry_but_other_channels_are_not
        """
        env = fx.draft_recall_env(api, schedule_notice=False)

        for channel in ("DIRECT_NOTICE", "PRESS_RELEASE", "WEB_POSTING"):
            notice = fx.create_notice(
                api, env["recall_id"], channel=channel, reach_count=500000
            )
            assert_field_values(
                notice, channel=channel, reach_count=500000, status="SCHEDULED"
            )

        _notices, meta = validate_paginated(
            api.list_consumer_notices(
                {"recall_id": env["recall_id"]}, headers=OFFICER_HEADERS
            )
        )
        assert meta["total_count"] == 3, (
            f"all three uncapped channels must be on file: {meta['total_count']}"
        )


class TestNegotiationRoundCap:
    """Six rounds, counted from both sides of the table and never handed back."""

    def test_the_seventh_offer_is_refused_after_six_alternating_rounds(self, api):
        """Agency and respondent offers draw from one shared allowance of six.

        The contract states: "The round counter is monotonic: it counts every
        offer entered into the record regardless of which side made it, is never
        decremented, and is capped at 6." And: "Next, `current_offer_round` must
        be strictly less than 6, otherwise `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`
        (HTTP 409) — the parties get six rounds and no more."

        Design: Corner/validations/negotiation_round_cap_counts_both_sides_and_is_never_decremented
        """
        env = fx.penalty_case_on_report_env(api, violation_count=4)
        case_id = env["case_id"]

        assert_field_values(
            env["case"],
            status="ASSESSMENT_OPEN",
            current_offer_round=0,
            assessed_penalty_cents=ASSESSED_PENALTY_CENTS,
        )

        table = (
            (5000000, "AGENCY", "OFFER_MADE"),
            (4000000, "RESPONDENT", "COUNTERED"),
            (4900000, "AGENCY", "OFFER_MADE"),
            (4100000, "RESPONDENT", "COUNTERED"),
            (4800000, "AGENCY", "OFFER_MADE"),
            (4200000, "RESPONDENT", "COUNTERED"),
        )
        for index, (amount_cents, offered_by, expected_status) in enumerate(table, 1):
            offered = _table_offer(api, case_id, amount_cents, offered_by)
            assert_field_values(
                offered,
                status=expected_status,
                current_offer_round=index,
                current_offer_cents=amount_cents,
                current_offer_by=offered_by,
            )
            assert_reserve_conserved(offered)

        exhausted = fx.get_penalty_case(api, case_id)
        response = api.create_offer(
            case_id,
            f.offer_payload(4700000, "AGENCY", exhausted["version"]),
            headers=COUNSEL_HEADERS,
        )

        validate_error(response, "ERR_NEGOTIATION_ROUNDS_EXHAUSTED", 409)

        after = fx.get_penalty_case(api, case_id)
        assert_field_values(
            after,
            status="COUNTERED",
            current_offer_round=6,
            current_offer_cents=4200000,
            current_offer_by="RESPONDENT",
            reserved_cents=0,
            available_cents=ASSESSED_PENALTY_CENTS,
        )
        assert_reserve_conserved(after)

    def test_six_withdrawn_offers_exhaust_the_negotiation_just_as_surely(self, api):
        """Withdrawal compensates the reserve exactly but never refunds the round.

        The contract states: "It pointedly does **not** give the round back: a
        withdrawn offer still consumed a round, so `current_offer_round` is left
        where it stands and six withdrawn offers exhaust the negotiation just as
        surely as six live ones." And: "What compensation never restores is a
        monotonic counter: a withdrawn offer still consumed a negotiation round,
        and a delinquency once recorded against a retailer stays recorded."

        Design: Corner/validations/negotiation_round_cap_counts_both_sides_and_is_never_decremented
        """
        env = fx.penalty_case_on_report_env(api, violation_count=4)
        case_id = env["case_id"]

        for index in range(1, 7):
            offered = _table_offer(api, case_id, 3000000 + index, "AGENCY")
            assert_field_values(
                offered, status="OFFER_MADE", current_offer_round=index
            )

            withdrawn = fx.resolve_offer(api, case_id, "WITHDRAWN")
            assert_field_values(
                withdrawn,
                status="ASSESSMENT_OPEN",
                current_offer_round=index,
                reserved_cents=0,
                available_cents=ASSESSED_PENALTY_CENTS,
            )
            assert_fields_null(withdrawn, "current_offer_cents", "current_offer_by")
            assert_reserve_conserved(withdrawn)

        spent = fx.get_penalty_case(api, case_id)
        response = api.create_offer(
            case_id,
            f.offer_payload(3000000, "AGENCY", spent["version"]),
            headers=COUNSEL_HEADERS,
        )

        validate_error(response, "ERR_NEGOTIATION_ROUNDS_EXHAUSTED", 409)

        after = fx.get_penalty_case(api, case_id)
        assert_field_values(
            after, status="ASSESSMENT_OPEN", current_offer_round=6
        )
        assert_reserve_conserved(after)
