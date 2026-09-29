"""A life-safety breach capped at ten days of cure, and the termination that closes the house."""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_field_equals,
    assert_item_state,
    assert_ledger_contains,
    assert_plan_dimensions,
    default_notice_payload,
    escalate_default_notice,
    issue_default_notice,
    issued_plan,
    ledger_entries,
    list_rows,
    plan_payload,
    read_franchisee,
    read_item,
    read_notice,
    read_plan,
    read_property,
    run_compliance_sweep,
    set_clock,
    validate_error,
)


@pytest.fixture
def swept_plan_with_one_overdue_life_safety_item(api):
    """A life-safety line read one day past its ninety-day date and recorded as overdue."""
    scenario = issued_plan(
        api,
        [
            {
                "key": "sprinklers",
                "category": "LIFE_SAFETY",
                "standards_reference": "LS-33.1.1",
                "brand_estimated_cost_cents": 2000000,
            }
        ],
        legal_name="Jerningham Hotels LLC",
        contact_email="ops@jerninghamh.example",
        property_overrides={"name": "Jerningham Old Wharf"},
    )
    set_clock(api, "2026-10-31T00:00:00Z")
    run_compliance_sweep(api, scenario.plan_id)
    return scenario


def _escalate_the_ten_day_notice(api, scenario):
    notice = issue_default_notice(api, scenario, 10)
    set_clock(api, "2026-11-11T00:00:00Z")
    escalate_default_notice(api, notice["id"])
    return notice


class TestLifeSafetyTightensTheCurePeriod:
    def test_eleven_days_of_cure_is_too_long_for_life_safety_scope(
        self, api, brand_manager, swept_plan_with_one_overdue_life_safety_item
    ):
        """"That count must be between 1 and 60 days inclusive, or the request fails with
        `ERR_CURE_PERIOD_OUT_OF_RANGE` (422). ... And where any of the plan's overdue items is a
        life-safety item, the cure period is tightened: `cure_period_days` may then not exceed 10 days,
        and a longer period is refused with `ERR_CURE_PERIOD_TOO_LONG_FOR_LIFE_SAFETY` (422)."

        Design: Corner/errors/life_safety_cure_ceiling_and_franchise_termination_guards_are_triggerable
        """
        scenario = swept_plan_with_one_overdue_life_safety_item

        response = api.create_default_notice(
            default_notice_payload(scenario.plan_id, 11), brand_manager
        )

        validate_error(response, ApiErrorId.ERR_CURE_PERIOD_TOO_LONG_FOR_LIFE_SAFETY, 422)
        _rows, meta = list_rows(api, "list_default_notices", plan_id=scenario.plan_id)
        assert meta["total_count"] == 0, f"the refused notice must persist nothing, got {meta}"
        assert_field_equals(
            read_property(api, scenario.property_id),
            "franchise_agreement_status",
            "ACTIVE",
            "property",
        )

    def test_ten_days_of_cure_is_admitted_and_prices_the_breach(
        self, api, swept_plan_with_one_overdue_life_safety_item
    ):
        """"Issuance creates the notice in `ISSUED` with `issued_by_user_id` set to the acting `X-User-ID`
        and `cure_deadline_date` set to the clock date advanced by `cure_period_days`." "each item's
        `approved_cost_cents` is multiplied by its category's damages rate — 0.15 for `LIFE_SAFETY`, 0.08
        for `GUEST_FACING`, 0.03 for `BACK_OF_HOUSE` — the exact per-item products are summed, and the
        total is rounded half up to whole cents **once, at the end**."

        Design: Corner/errors/life_safety_cure_ceiling_and_franchise_termination_guards_are_triggerable
        """
        scenario = swept_plan_with_one_overdue_life_safety_item

        notice = issue_default_notice(api, scenario, 10)

        assert_field_equals(notice, "status", "ISSUED", "notice")
        assert_field_equals(notice, "cure_deadline_date", "2026-11-10", "notice")
        assert_field_equals(notice, "liquidated_damages_cents", 300000, "notice")
        assert_field_equals(notice, "issued_by_user_id", "bm-001", "notice")
        assert notice["breached_item_ids"] == [scenario.item_id("sprinklers")], (
            f"the one overdue life-safety line is the whole breach, got {notice!r}"
        )


class TestEscalationTerminatesThePlanAndTheAgreement:
    def test_the_escalation_voids_the_plan_and_its_scope(
        self, api, swept_plan_with_one_overdue_life_safety_item
    ):
        """"Link one moves the plan's `status` to `TERMINATED` and increments the plan's `version` by one.
        Link two, caused by link one, voids and cancels the plan's children: every item of the plan whose
        `status` is `SCOPED`, `DEFERRED_PENDING_EXTENSION`, `IN_PROGRESS`, `WORK_COMPLETE` or `PUNCH_FAIL`
        becomes `VOIDED` and thereby leaves every plan aggregate". "A ledger entry of type
        `PLAN_TERMINATED` is appended with a null item reference and a `delta_cents` of 0."

        Design: Corner/errors/life_safety_cure_ceiling_and_franchise_termination_guards_are_triggerable
        """
        scenario = swept_plan_with_one_overdue_life_safety_item

        notice = _escalate_the_ten_day_notice(api, scenario)

        assert_field_equals(
            read_notice(api, notice["id"]), "status", "ESCALATED_TO_TERMINATION", "notice"
        )
        assert_plan_dimensions(read_plan(api, scenario.plan_id), status="TERMINATED")
        assert_item_state(read_item(api, scenario.item_id("sprinklers")), status="VOIDED")
        assert_ledger_contains(
            ledger_entries(api, plan_id=scenario.plan_id),
            "PLAN_TERMINATED",
            delta_cents=0,
            count=1,
        )

    def test_the_termination_reaches_the_property_and_the_franchisee(
        self, api, swept_plan_with_one_overdue_life_safety_item
    ):
        """"Link four, caused by link one, sets the property's `franchise_agreement_status` to
        `TERMINATED`. Link five, caused by link four, sets the property's `compliance_posture` to
        `TERMINATED` and the franchisee's `standing` to `TERMINATED_PORTFOLIO`."

        Design: Corner/errors/life_safety_cure_ceiling_and_franchise_termination_guards_are_triggerable
        """
        scenario = swept_plan_with_one_overdue_life_safety_item
        _escalate_the_ten_day_notice(api, scenario)

        prop = read_property(api, scenario.property_id)

        assert_field_equals(prop, "franchise_agreement_status", "TERMINATED", "property")
        assert_field_equals(prop, "compliance_posture", "TERMINATED", "property")
        assert_field_equals(
            read_franchisee(api, scenario.franchisee_id),
            "standing",
            "TERMINATED_PORTFOLIO",
            "franchisee",
        )

    def test_a_terminated_house_refuses_a_fresh_plan_outright(
        self, api, brand_manager, swept_plan_with_one_overdue_life_safety_item
    ):
        """"Once the property's franchise agreement is terminated, no new plan, item, budget, phase or
        draw may be created against it." "A plan may not be scoped against a property whose
        `franchise_agreement_status` is `TERMINATED`; that attempt, like item creation, budget creation,
        phase creation and draw creation on such a property, is refused with `ERR_FRANCHISE_TERMINATED`."

        Design: Corner/errors/life_safety_cure_ceiling_and_franchise_termination_guards_are_triggerable
        """
        scenario = swept_plan_with_one_overdue_life_safety_item
        _escalate_the_ten_day_notice(api, scenario)

        response = api.create_plan(
            plan_payload(scenario.property_id, "RELICENSING", "2026.1"), brand_manager
        )

        validate_error(response, ApiErrorId.ERR_FRANCHISE_TERMINATED, 409)
        _rows, meta = list_rows(api, "list_plans", property_id=scenario.property_id)
        assert meta["total_count"] == 1, f"the refused scoping must add no plan, got {meta}"
