"""Certification refused while work is in flight, and the closed budget that freezes a payment."""

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
    consent_draw,
    disburse_draw,
    ledger_entries,
    locked_budget,
    perform_inspection,
    read_budget,
    read_draw,
    read_inspection,
    read_item,
    read_plan,
    read_property,
    request_draw,
    schedule_inspection,
    sign_off_inspection,
    start_item,
    validate_error,
)


@pytest.fixture
def running_work_with_a_paid_draw_and_a_performed_visit(api):
    """One item still in flight, a hundred thousand cents already paid, the visit recorded."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "corridors",
                "category": "GUEST_FACING",
                "standards_reference": "GF-32.1.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
        legal_name="Inglemere Hotels LLC",
        contact_email="ops@inglemereh.example",
        property_overrides={"name": "Inglemere Cathedral Green"},
    )
    budget = locked_budget(api, scenario, 1182500, financing_source="RESERVE_DRAW")
    start_item(api, scenario, scenario.item_id("corridors"))
    draw = request_draw(
        api, scenario, budget["id"], scenario.item_id("corridors"), 100000
    )
    consent_draw(api, draw["id"])
    draw = disburse_draw(api, scenario, draw["id"])
    inspection = schedule_inspection(api, scenario, scheduled_date="2026-08-01")
    inspection = perform_inspection(api, inspection["id"])
    return scenario, budget, draw, inspection


def _finish_the_work_and_certify(api, scenario, inspection):
    complete_item_work(api, scenario, scenario.item_id("corridors"))
    return sign_off_inspection(api, inspection["id"])


class TestCertificationWaitsForEveryItem:
    def test_signoff_is_refused_while_the_item_is_still_in_flight(
        self, api, brand_inspector, running_work_with_a_paid_draw_and_a_performed_visit
    ):
        """"The plan's `status` must be `READY_FOR_COMPLETION_INSPECTION`, or
        `ERR_PLAN_NOT_READY_FOR_SIGNOFF`."

        Design: Corner/errors/completion_signoff_closes_the_budget_and_freezes_reversals
        """
        scenario, _budget, _draw, inspection = (
            running_work_with_a_paid_draw_and_a_performed_visit
        )

        response = api.sign_off_inspection(inspection["id"], brand_inspector)

        validate_error(response, ApiErrorId.ERR_PLAN_NOT_READY_FOR_SIGNOFF, 409)
        read_back = read_inspection(api, inspection["id"])
        assert_field_equals(read_back, "status", "PERFORMED", "inspection")
        assert read_back["signed_off_at"] is None, (
            f"a refused certification stamps no signature, got {read_back!r}"
        )
        assert_plan_dimensions(read_plan(api, scenario.plan_id), status="IN_EXECUTION")

    def test_the_certification_stamps_the_signing_inspector(
        self, api, running_work_with_a_paid_draw_and_a_performed_visit
    ):
        """"A successful sign-off moves the inspection `PERFORMED → SIGNED_OFF`, stamping `signed_off_at`
        with the logical clock and `signed_off_by_user_id` with the acting `X-User-ID`, and drives the
        plan's completion cascade in full."

        Design: Corner/errors/completion_signoff_closes_the_budget_and_freezes_reversals
        """
        scenario, _budget, _draw, inspection = (
            running_work_with_a_paid_draw_and_a_performed_visit
        )

        signed = _finish_the_work_and_certify(api, scenario, inspection)

        assert_field_equals(signed, "status", "SIGNED_OFF", "inspection")
        assert_field_equals(signed, "signed_off_by_user_id", "bi-007", "inspection")
        assert signed["signed_off_at"] is not None, (
            f"certification stamps the logical clock, got {signed!r}"
        )

    def test_the_completion_cascade_accepts_the_scope_and_clears_the_house(
        self, api, running_work_with_a_paid_draw_and_a_performed_visit
    ):
        """"The plan moves `READY_FOR_COMPLETION_INSPECTION → COMPLETED` and its `version` increments.
        Every item of the plan still in `WORK_COMPLETE` becomes `ACCEPTED`, each with its `version`
        incremented." "Finally the property's `open_plan_count`, `compliance_risk_score` and
        `compliance_posture` are recomputed, followed by the franchisee's `standing`."

        Design: Corner/errors/completion_signoff_closes_the_budget_and_freezes_reversals
        """
        scenario, _budget, _draw, inspection = (
            running_work_with_a_paid_draw_and_a_performed_visit
        )
        _finish_the_work_and_certify(api, scenario, inspection)

        assert_plan_dimensions(read_plan(api, scenario.plan_id), status="COMPLETED")
        assert_item_state(read_item(api, scenario.item_id("corridors")), status="ACCEPTED")
        prop = read_property(api, scenario.property_id)
        assert_field_equals(prop, "open_plan_count", 0, "property")
        assert_posture(prop, 100, "COMPLIANT")

    def test_the_closed_budget_freezes_the_amount_already_committed(
        self, api, running_work_with_a_paid_draw_and_a_performed_visit
    ):
        """"The plan's active capital budget — whichever of `APPROVED`, `LOCKED` or `UNDERFUNDED` it
        holds — becomes `CLOSED`, freezing `committed_cents`. A ledger entry of type `PLAN_COMPLETED` is
        appended with a null item reference and a `delta_cents` of 0."

        Design: Corner/errors/completion_signoff_closes_the_budget_and_freezes_reversals
        """
        scenario, budget, _draw, inspection = (
            running_work_with_a_paid_draw_and_a_performed_visit
        )
        _finish_the_work_and_certify(api, scenario, inspection)

        stored = read_budget(api, budget["id"])

        assert_field_equals(stored, "status", "CLOSED", "budget")
        assert_field_equals(stored, "committed_cents", 100000, "budget")
        assert_field_equals(
            read_property(api, scenario.property_id),
            "reserve_balance_cents",
            49900000,
            "property",
        )
        assert_ledger_contains(
            ledger_entries(api, plan_id=scenario.plan_id),
            "PLAN_COMPLETED",
            delta_cents=0,
            count=1,
        )

    def test_a_disbursement_can_no_longer_be_unwound_once_the_budget_closes(
        self, api, running_work_with_a_paid_draw_and_a_performed_visit
    ):
        """"It is refused unless the draw is in `DISBURSED` (`ERR_DRAW_NOT_REVERSIBLE`), unless the acting
        `X-User-ID` is the property's `franchisee_id`, and unless the funding budget is not `CLOSED`
        (`ERR_BUDGET_CLOSED`) — once plan completion or termination has closed the budget, the
        disbursement can no longer be unwound."

        Design: Corner/errors/completion_signoff_closes_the_budget_and_freezes_reversals
        """
        scenario, _budget, draw, inspection = (
            running_work_with_a_paid_draw_and_a_performed_visit
        )
        _finish_the_work_and_certify(api, scenario, inspection)

        response = api.reverse_reserve_draw(draw["id"], scenario.owner_headers)

        validate_error(response, ApiErrorId.ERR_BUDGET_CLOSED, 409)
        assert_field_equals(read_draw(api, draw["id"]), "status", "DISBURSED", "draw")
        assert_field_equals(
            read_property(api, scenario.property_id),
            "reserve_balance_cents",
            49900000,
            "property",
        )

    def test_the_disbursement_was_booked_before_the_plan_closed(
        self, api, running_work_with_a_paid_draw_and_a_performed_visit
    ):
        """"On success the draw's `amount_cents` is subtracted from `reserve_balance_cents` and the
        property's `version` increments; `disbursed_at` is stamped with the logical clock; the funding
        budget's `committed_cents` increases by the same amount; and a ledger entry of type
        `DRAW_DISBURSED` is appended, carrying the draw's `purpose_item_id` as its item reference and the
        draw amount as a positive `delta_cents`."

        Design: Corner/errors/completion_signoff_closes_the_budget_and_freezes_reversals
        """
        scenario, _budget, draw, _inspection = (
            running_work_with_a_paid_draw_and_a_performed_visit
        )

        assert_field_equals(draw, "status", "DISBURSED", "draw")
        assert draw["disbursed_at"] is not None, (
            f"a paid draw carries the clock instant it left, got {draw!r}"
        )
        assert_ledger_contains(
            ledger_entries(api, plan_id=scenario.plan_id),
            "DRAW_DISBURSED",
            delta_cents=100000,
            item_id=scenario.item_id("corridors"),
            count=1,
        )
