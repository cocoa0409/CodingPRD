"""The cure and escalation branches of one notice, and a defect charged across plan lines."""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    acknowledged_plan,
    assert_field_equals,
    assert_item_state,
    assert_ledger_contains,
    assert_plan_dimensions,
    assert_posture,
    complete_item_work,
    cure_default_notice,
    issue_default_notice,
    issue_plan,
    ledger_entries,
    list_rows,
    locked_budget,
    performed_completion_inspection,
    punch_list_item_payload,
    read_franchisee,
    read_inspection,
    read_item,
    read_notice,
    read_plan,
    read_property,
    run_compliance_sweep,
    scope_plan,
    set_clock,
    start_item,
    validate_error,
)


@pytest.fixture
def noticed_plan_under_a_thirty_day_cure(api):
    """One guest-facing item read a day past due, and a default notice issued over it."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "corridors",
                "category": "GUEST_FACING",
                "standards_reference": "GF-26.1.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
        legal_name="Cranleigh Hotels LLC",
        contact_email="ops@cranleighh.example",
    )
    locked_budget(api, scenario, 1182500)
    set_clock(api, "2027-04-29T00:00:00Z")
    run_compliance_sweep(api, scenario.plan_id)
    notice = issue_default_notice(api, scenario, 30)
    return scenario, notice


def _finish_the_breached_work(api, scenario):
    start_item(api, scenario, scenario.item_id("corridors"))
    complete_item_work(api, scenario, scenario.item_id("corridors"))


class TestNoticeCureAndEscalationAreEachConditional:
    def test_the_notice_dates_the_cure_period_from_the_clock(
        self, api, noticed_plan_under_a_thirty_day_cure
    ):
        """"Issuance creates the notice in `ISSUED` with `issued_by_user_id` set to the acting
        `X-User-ID` and `cure_deadline_date` set to the clock date advanced by `cure_period_days`." "It
        snapshots `breached_item_ids` as the ids of every item of the plan whose overdue flag is true at
        that instant, ordered by `priority_rank` ascending".

        Design: Corner/endpoints/default_notice_cure_and_escalation_are_each_conditional
        """
        scenario, notice = noticed_plan_under_a_thirty_day_cure

        assert_field_equals(notice, "status", "ISSUED", "notice")
        assert_field_equals(notice, "cure_deadline_date", "2027-05-29", "notice")
        assert_field_equals(notice, "liquidated_damages_cents", 80000, "notice")
        assert notice["breached_item_ids"] == [scenario.item_id("corridors")], (
            f"the single overdue guest-facing item is the whole breach, got {notice!r}"
        )

    def test_neither_branch_is_open_while_the_work_is_undone(
        self, api, brand_manager, noticed_plan_under_a_thirty_day_cure
    ):
        """"The action is refused unless the notice is in `ISSUED` (`ERR_NOTICE_NOT_ACTIONABLE`) and
        unless *every* item id in `breached_item_ids` now holds a `status` of `WORK_COMPLETE`,
        `ACCEPTED` or `REMOVED_BY_DISPUTE` — a single laggard yields `ERR_BREACH_NOT_CURED` (409)."
        "unless the clock date is *strictly* later than the notice's `cure_deadline_date` — on the
        deadline date itself escalation is refused with `ERR_CURE_PERIOD_NOT_ELAPSED` (409)".

        Design: Corner/endpoints/default_notice_cure_and_escalation_are_each_conditional
        """
        scenario, notice = noticed_plan_under_a_thirty_day_cure

        validate_error(
            api.cure_default_notice(notice["id"], brand_manager),
            ApiErrorId.ERR_BREACH_NOT_CURED,
            409,
        )
        validate_error(
            api.escalate_default_notice(notice["id"], brand_manager),
            ApiErrorId.ERR_CURE_PERIOD_NOT_ELAPSED,
            409,
        )

        assert_field_equals(read_notice(api, notice["id"]), "status", "ISSUED", "notice")
        assert_item_state(read_item(api, scenario.item_id("corridors")), status="SCOPED")

    def test_finished_work_bars_escalation_even_once_the_period_has_run(
        self, api, brand_manager, noticed_plan_under_a_thirty_day_cure
    ):
        """"and unless at least one item id in `breached_item_ids` still holds a `status` outside
        `WORK_COMPLETE`, `ACCEPTED` and `REMOVED_BY_DISPUTE`, since a fully cured breach cannot be
        escalated and yields `ERR_BREACH_ALREADY_CURED` (409)."

        Design: Corner/endpoints/default_notice_cure_and_escalation_are_each_conditional
        """
        scenario, notice = noticed_plan_under_a_thirty_day_cure
        _finish_the_breached_work(api, scenario)
        set_clock(api, "2027-05-30T00:00:00Z")

        validate_error(
            api.escalate_default_notice(notice["id"], brand_manager),
            ApiErrorId.ERR_BREACH_ALREADY_CURED,
            409,
        )

        assert_field_equals(read_notice(api, notice["id"]), "status", "ISSUED", "notice")
        assert_plan_dimensions(
            read_plan(api, scenario.plan_id), status="READY_FOR_COMPLETION_INSPECTION"
        )

    def test_the_cure_restores_the_agreement_and_the_owners_standing(
        self, api, noticed_plan_under_a_thirty_day_cure
    ):
        """"On success the property's `franchise_agreement_status` returns to `ACTIVE`, but only once no
        other notice of that property remains `ISSUED`; the property's `compliance_risk_score` and
        `compliance_posture` are recomputed and then the franchisee's `standing`; and a ledger entry of
        type `DEFAULT_CURED` is appended."

        Design: Corner/endpoints/default_notice_cure_and_escalation_are_each_conditional
        """
        scenario, notice = noticed_plan_under_a_thirty_day_cure
        _finish_the_breached_work(api, scenario)

        cured = cure_default_notice(api, notice["id"])

        assert_field_equals(cured, "status", "CURED", "notice")
        prop = read_property(api, scenario.property_id)
        assert_field_equals(prop, "franchise_agreement_status", "ACTIVE", "property")
        assert_posture(prop, 100, "COMPLIANT")
        assert_field_equals(
            read_franchisee(api, scenario.franchisee_id), "standing", "GOOD", "franchisee"
        )
        assert_ledger_contains(
            ledger_entries(api, plan_id=scenario.plan_id), "DEFAULT_CURED", count=1
        )

    def test_a_cured_notice_is_inert_to_a_second_attempt(
        self, api, brand_manager, noticed_plan_under_a_thirty_day_cure
    ):
        """"`CURED` and `ESCALATED_TO_TERMINATION` are the terminal notice states." "The action is
        refused unless the notice is in `ISSUED` (`ERR_NOTICE_NOT_ACTIONABLE`)".

        Design: Corner/endpoints/default_notice_cure_and_escalation_are_each_conditional
        """
        scenario, notice = noticed_plan_under_a_thirty_day_cure
        _finish_the_breached_work(api, scenario)
        cure_default_notice(api, notice["id"])

        validate_error(
            api.cure_default_notice(notice["id"], brand_manager),
            ApiErrorId.ERR_NOTICE_NOT_ACTIONABLE,
            409,
        )

        assert_field_equals(read_notice(api, notice["id"]), "status", "CURED", "notice")
        assert_item_state(
            read_item(api, scenario.item_id("corridors")), status="WORK_COMPLETE"
        )


@pytest.fixture
def one_inspection_and_a_second_plan_on_the_same_house(api):
    """A completed first plan carrying a performed inspection, beside a freshly issued second plan."""
    built = performed_completion_inspection(
        api,
        [
            {
                "key": "lobby",
                "category": "GUEST_FACING",
                "standards_reference": "GF-27.1.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
        1182500,
        scheduled_date="2026-08-01",
        perform_at_utc="2026-08-01T00:00:00Z",
        legal_name="Duncroft Hotels LLC",
        contact_email="ops@duncrofth.example",
    )
    first = built["scenario"]
    second = scope_plan(
        api,
        first.portfolio,
        [
            {
                "key": "signage",
                "category": "GUEST_FACING",
                "standards_reference": "GF-27.2.1",
                "brand_estimated_cost_cents": 400000,
            }
        ],
        trigger_type="RELICENSING",
    )
    second = issue_plan(api, second)
    return first, second, built["inspection"]


class TestPunchDefectsStayInsideTheirOwnPlan:
    def test_a_defect_may_not_be_charged_to_an_item_of_another_plan(
        self, api, brand_inspector, one_inspection_and_a_second_plan_on_the_same_house
    ):
        """"The charged `pip_item_id` must belong to the plan of the named inspection, or the filing
        fails with `ERR_ITEM_PLAN_MISMATCH` (422)."

        Design: Corner/endpoints/punch_item_from_another_plan_is_rejected
        """
        _first, second, inspection = one_inspection_and_a_second_plan_on_the_same_house

        response = api.create_punch_list_item(
            punch_list_item_payload(
                inspection["id"],
                second.item_id("signage"),
                severity="MAJOR",
                defect_note="Lobby feature wall panels delaminating at the reveal joints.",
            ),
            brand_inspector,
        )

        validate_error(response, ApiErrorId.ERR_ITEM_PLAN_MISMATCH, 422)
        _rows, meta = list_rows(api, "list_punch_list_items", inspection_id=inspection["id"])
        assert meta["total_count"] == 0, f"the refused filing must leave no defect, got {meta}"

    def test_the_refusal_leaves_the_inspection_and_both_plans_untouched(
        self, api, brand_inspector, one_inspection_and_a_second_plan_on_the_same_house
    ):
        """"The defect is created in `OPEN` with `verification_note` null and with `cure_deadline_date`
        set to the clock date advanced by 14 days. The raising inspection's `punch_open_count` increases
        by one". "Performing stamps `performed_at` with the logical clock and recomputes
        `punch_open_count`, which is 0 until defects are filed."

        Design: Corner/endpoints/punch_item_from_another_plan_is_rejected
        """
        first, second, inspection = one_inspection_and_a_second_plan_on_the_same_house
        validate_error(
            api.create_punch_list_item(
                punch_list_item_payload(
                    inspection["id"],
                    second.item_id("signage"),
                    severity="MAJOR",
                    defect_note="Lobby feature wall panels delaminating at the reveal joints.",
                ),
                brand_inspector,
            ),
            ApiErrorId.ERR_ITEM_PLAN_MISMATCH,
            422,
        )

        read_back = read_inspection(api, inspection["id"])

        assert_field_equals(read_back, "punch_open_count", 0, "inspection")
        assert_field_equals(read_back, "status", "PERFORMED", "inspection")
        assert_item_state(read_item(api, first.item_id("lobby")), status="WORK_COMPLETE")
        assert_item_state(read_item(api, second.item_id("signage")), status="SCOPED")
        assert_plan_dimensions(
            read_plan(api, first.plan_id), status="READY_FOR_COMPLETION_INSPECTION"
        )
        assert_plan_dimensions(read_plan(api, second.plan_id), status="ISSUED")


class TestASecondPlanRidesAlongsideTheFirst:
    def test_the_relicensing_plan_is_issued_without_disturbing_the_finished_one(
        self, api, one_inspection_and_a_second_plan_on_the_same_house
    ):
        """"It stamps the three category deadlines from the date of `issued_at`:
        `life_safety_deadline_date` 90 calendar days out, `guest_facing_deadline_date` 270 calendar days
        out, and `back_of_house_deadline_date` 450 calendar days out."

        Design: Corner/endpoints/punch_item_from_another_plan_is_rejected
        """
        _first, second, _inspection = one_inspection_and_a_second_plan_on_the_same_house

        plan = read_plan(api, second.plan_id)

        assert_field_equals(plan, "guest_facing_deadline_date", "2027-04-28", "second plan")
        assert_field_equals(plan, "scope_item_count", 1, "second plan")
        assert_field_equals(plan, "brand_scoped_total_cents", 400000, "second plan")
        assert_item_state(
            read_item(api, second.item_id("signage")), deadline_date="2027-04-28"
        )
