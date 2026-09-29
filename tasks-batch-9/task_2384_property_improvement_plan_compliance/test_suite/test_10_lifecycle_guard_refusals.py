"""The refusals that keep a plan's lifecycle one-way: acknowledge, re-issue, withdraw, inspect."""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_field_equals,
    assert_item_state,
    assert_ledger_contains,
    assert_plan_dimensions,
    assert_posture,
    bootstrap_portfolio,
    get_success_data,
    issued_plan,
    item_payload,
    ledger_entries,
    list_rows,
    perform_inspection,
    read_inspection,
    read_item,
    read_plan,
    read_property,
    schedule_inspection,
    scope_plan,
    set_clock,
    validate_error,
)


@pytest.fixture
def draft_plan_awaiting_issuance(api):
    """A scoped but still unissued plan carrying one life-safety item."""
    portfolio = bootstrap_portfolio(
        api, "Northbridge Hotels LLC", "asset@northbridgehotels.example"
    )
    return scope_plan(
        api,
        portfolio,
        [
            {
                "key": "extinguishers",
                "category": "LIFE_SAFETY",
                "standards_reference": "LS-8.1.1",
                "brand_estimated_cost_cents": 100000,
            }
        ],
    )


class TestAcknowledgementNeedsAnIssuedPlan:
    def test_acknowledging_a_draft_plan_is_refused(self, api, draft_plan_awaiting_issuance):
        """"The owner's contractual receipt moves the plan `ISSUED → OWNER_ACKNOWLEDGED` and opens
        the execution window. It is refused from any other state with
        `ERR_PLAN_NOT_ACKNOWLEDGEABLE`".

        Design: Corner/state_machines/acknowledge_on_a_draft_plan_is_rejected
        """
        scenario = draft_plan_awaiting_issuance

        response = api.acknowledge_plan(scenario.plan_id, scenario.owner_headers)

        validate_error(response, ApiErrorId.ERR_PLAN_NOT_ACKNOWLEDGEABLE, 409)
        assert_plan_dimensions(
            read_plan(api, scenario.plan_id), status="DRAFT", dispute_state="NONE"
        )

    def test_the_refused_receipt_stamps_no_deadline_anywhere(
        self, api, draft_plan_awaiting_issuance
    ):
        """"The plan is born with `status` at `DRAFT` and `dispute_state` at `NONE`, with
        `issued_by_user_id` and `issued_at` null, with all three category deadline dates null".
        "Items of a draft plan have a null `deadline_date` and are never overdue."

        Design: Corner/state_machines/acknowledge_on_a_draft_plan_is_rejected
        """
        scenario = draft_plan_awaiting_issuance
        validate_error(
            api.acknowledge_plan(scenario.plan_id, scenario.owner_headers),
            ApiErrorId.ERR_PLAN_NOT_ACKNOWLEDGEABLE,
            409,
        )

        plan = read_plan(api, scenario.plan_id)
        item = read_item(api, scenario.item_id("extinguishers"))

        assert plan["life_safety_deadline_date"] is None, (
            f"a draft plan carries no life-safety deadline, got {plan!r}"
        )
        assert_item_state(item, status="SCOPED", is_overdue=False)
        assert item["deadline_date"] is None, f"unexpected item deadline in {item!r}"
        assert_field_equals(
            read_property(api, scenario.property_id), "open_plan_count", 0, "property"
        )


@pytest.fixture
def issued_plan_a_month_later(api):
    """A plan issued at the default clock, then read again a month further on."""
    scenario = issued_plan(
        api,
        [
            {
                "key": "lobby",
                "category": "GUEST_FACING",
                "standards_reference": "GF-8.8.1",
                "brand_estimated_cost_cents": 800000,
            }
        ],
        legal_name="Oakhollow Lodging LLC",
        contact_email="pm@oakhollowlodging.example",
    )
    set_clock(api, "2026-09-01T00:00:00Z")
    return scenario


class TestIssuanceIsNotRepeatable:
    def test_a_second_issue_on_an_issued_plan_is_refused(self, api, brand_manager, issued_plan_a_month_later):
        """"Issuing the plan is the brand's act of freezing the scope and starting the clock, and it
        is refused unless the plan is `DRAFT` (`ERR_PLAN_NOT_ISSUABLE`)".

        Design: Corner/state_machines/second_issue_on_an_issued_plan_is_rejected
        """
        scenario = issued_plan_a_month_later

        response = api.issue_plan(scenario.plan_id, brand_manager)

        validate_error(response, ApiErrorId.ERR_PLAN_NOT_ISSUABLE, 409)
        assert_plan_dimensions(read_plan(api, scenario.plan_id), status="ISSUED")

    def test_the_refused_issue_moves_no_stamp_and_no_deadline(
        self, api, brand_manager, issued_plan_a_month_later
    ):
        """"It stamps `issued_by_user_id` with the acting operator's `X-User-ID` — the id thereby
        barred from certifying this plan's completion — and `issued_at` with the logical clock." "It
        stamps the three category deadlines from the date of `issued_at`: `life_safety_deadline_date`
        90 calendar days out, `guest_facing_deadline_date` 270 calendar days out, and
        `back_of_house_deadline_date` 450 calendar days out."

        Design: Corner/state_machines/second_issue_on_an_issued_plan_is_rejected
        """
        scenario = issued_plan_a_month_later
        validate_error(
            api.issue_plan(scenario.plan_id, brand_manager),
            ApiErrorId.ERR_PLAN_NOT_ISSUABLE,
            409,
        )

        plan = read_plan(api, scenario.plan_id)

        assert plan["issued_at"] == "2026-08-01T00:00:00Z", (
            f"the issuance instant must stay at the original clock reading, got {plan!r}"
        )
        assert_field_equals(plan, "guest_facing_deadline_date", "2027-04-28", "plan")

    def test_only_one_scope_issued_row_was_ever_appended(
        self, api, brand_manager, issued_plan_a_month_later
    ):
        """"It appends a ledger entry of type `SCOPE_ISSUED` with a null item reference and a
        `delta_cents` equal to the plan's brand-scoped total." "Finally it recomputes the property's
        `open_plan_count`, `compliance_risk_score` and `compliance_posture`".

        Design: Corner/state_machines/second_issue_on_an_issued_plan_is_rejected
        """
        scenario = issued_plan_a_month_later
        validate_error(
            api.issue_plan(scenario.plan_id, brand_manager),
            ApiErrorId.ERR_PLAN_NOT_ISSUABLE,
            409,
        )

        assert_ledger_contains(
            ledger_entries(api, plan_id=scenario.plan_id),
            "SCOPE_ISSUED",
            delta_cents=800000,
            item_id=None,
            count=1,
        )
        assert_field_equals(
            read_property(api, scenario.property_id), "open_plan_count", 1, "property"
        )


@pytest.fixture
def withdrawn_plan(api, brand_manager):
    """A plan issued and then withdrawn by the brand, with its one item voided."""
    scenario = issued_plan(
        api,
        [
            {
                "key": "loading_dock",
                "category": "BACK_OF_HOUSE",
                "standards_reference": "BOH-9.9.1",
                "brand_estimated_cost_cents": 250000,
            }
        ],
        legal_name="Pearlstone Hospitality LLC",
        contact_email="counsel@pearlstonehospitality.example",
    )
    get_success_data(api.withdraw_plan(scenario.plan_id, brand_manager))
    return scenario


class TestWithdrawnPlanIsLockedDown:
    def test_neither_withdrawal_nor_acknowledgement_may_be_repeated(self, api, brand_manager, withdrawn_plan):
        """"The brand may withdraw a plan while its `status` is either `DRAFT` or `ISSUED`; from any
        other state the request is refused with `ERR_PLAN_NOT_WITHDRAWABLE`." "It is refused from any
        other state with `ERR_PLAN_NOT_ACKNOWLEDGEABLE`".

        Design: Corner/state_machines/withdrawn_plan_is_locked_down_against_every_trigger
        """
        scenario = withdrawn_plan

        validate_error(
            api.withdraw_plan(scenario.plan_id, brand_manager),
            ApiErrorId.ERR_PLAN_NOT_WITHDRAWABLE,
            409,
        )
        validate_error(
            api.acknowledge_plan(scenario.plan_id, scenario.owner_headers),
            ApiErrorId.ERR_PLAN_NOT_ACKNOWLEDGEABLE,
            409,
        )
        assert_plan_dimensions(read_plan(api, scenario.plan_id), status="WITHDRAWN")

    def test_neither_scope_edits_nor_work_may_start_on_it(self, api, brand_manager, withdrawn_plan):
        """"Scope is then filled in item by item, and only while the plan is `DRAFT` — an attempt to
        add or revise an item after issuance is refused with `ERR_PLAN_NOT_DRAFT`." "The item must be
        in `SCOPED`, or the request fails with `ERR_ITEM_NOT_STARTABLE`."

        Design: Corner/state_machines/withdrawn_plan_is_locked_down_against_every_trigger
        """
        scenario = withdrawn_plan

        validate_error(
            api.create_item(
                item_payload(
                    scenario.plan_id,
                    category="BACK_OF_HOUSE",
                    standards_reference="BOH-9.9.2",
                    brand_estimated_cost_cents=100000,
                ),
                brand_manager,
            ),
            ApiErrorId.ERR_PLAN_NOT_DRAFT,
            409,
        )
        validate_error(
            api.start_item(scenario.item_id("loading_dock"), scenario.owner_headers),
            ApiErrorId.ERR_ITEM_NOT_STARTABLE,
            409,
        )
        assert_item_state(read_item(api, scenario.item_id("loading_dock")), status="VOIDED")

    def test_the_voided_item_leaves_the_aggregates_but_not_the_collection(
        self, api, withdrawn_plan
    ):
        """"Both source states behave identically: `DRAFT → WITHDRAWN` and `ISSUED → WITHDRAWN` each
        void every item of the plan whose `status` is `SCOPED` or `DEFERRED_PENDING_EXTENSION`,
        recompute the property's `open_plan_count`, `compliance_risk_score` and `compliance_posture`
        and then the franchisee's `standing`, and increment the plan's `version` by one." "The
        included set is every item of the plan whose `status` is neither `REMOVED_BY_DISPUTE` nor
        `VOIDED`."

        Design: Corner/state_machines/withdrawn_plan_is_locked_down_against_every_trigger
        """
        scenario = withdrawn_plan

        plan = read_plan(api, scenario.plan_id)
        _rows, meta = list_rows(api, "list_items", plan_id=scenario.plan_id)

        assert_field_equals(plan, "scope_item_count", 0, "plan")
        assert_field_equals(plan, "brand_scoped_total_cents", 0, "plan")
        assert meta["total_count"] == 1, (
            f"the voided item is still a row of the plan's item collection, got {meta}"
        )
        prop = read_property(api, scenario.property_id)
        assert_field_equals(prop, "open_plan_count", 0, "property")
        assert_posture(prop, 100, "COMPLIANT")


@pytest.fixture
def inspection_scheduled_for_september(api):
    """A progress visit booked for 2026-09-10 while the clock still reads the default instant."""
    scenario = issued_plan(
        api,
        [
            {
                "key": "corridors",
                "category": "GUEST_FACING",
                "standards_reference": "GF-6.1.1",
                "brand_estimated_cost_cents": 900000,
            }
        ],
        legal_name="Rosewater Hotels LLC",
        contact_email="quality@rosewaterhotels.example",
    )
    inspection = schedule_inspection(
        api, scenario, scheduled_date="2026-09-10", inspection_type="PROGRESS"
    )
    return scenario, inspection


class TestInspectionTemporalWindow:
    def test_performing_before_the_scheduled_date_is_refused(
        self, api, brand_inspector, inspection_scheduled_for_september
    ):
        """"The action is refused unless the inspection is in `SCHEDULED`
        (`ERR_INSPECTION_NOT_PERFORMABLE`), unless the acting `X-User-ID` equals the inspection's
        `inspector_user_id` (`ERR_NOT_ASSIGNED_INSPECTOR`), and unless the clock date is at or after
        the inspection's `scheduled_date` (`ERR_INSPECTION_TOO_EARLY`) — a visit may be recorded on
        its scheduled date or later, never before."

        Design: Corner/state_machines/inspection_perform_before_its_scheduled_date_is_rejected
        """
        scenario, inspection = inspection_scheduled_for_september

        response = api.perform_inspection(inspection["id"], brand_inspector)

        validate_error(response, ApiErrorId.ERR_INSPECTION_TOO_EARLY, 409)
        refused = read_inspection(api, inspection["id"])
        assert_field_equals(refused, "status", "SCHEDULED", "inspection")
        assert refused["performed_at"] is None, (
            f"a refused visit may not stamp performed_at, got {refused['performed_at']!r}"
        )
        assert_plan_dimensions(read_plan(api, scenario.plan_id), status="ISSUED")

    def test_performing_on_the_scheduled_date_itself_is_admitted(
        self, api, inspection_scheduled_for_september
    ):
        """"The assigned inspector records the visit as performed, moving it `SCHEDULED →
        PERFORMED`." "Performing stamps `performed_at` with the logical clock and recomputes
        `punch_open_count`, which is 0 until defects are filed."

        Design: Corner/state_machines/inspection_perform_before_its_scheduled_date_is_rejected
        """
        _scenario, inspection = inspection_scheduled_for_september
        set_clock(api, "2026-09-10T00:00:00Z")

        performed = perform_inspection(api, inspection["id"])

        assert_field_equals(performed, "status", "PERFORMED", "inspection")
        assert_field_equals(performed, "punch_open_count", 0, "inspection")
        assert performed["performed_at"] == "2026-09-10T00:00:00Z", (
            f"performed_at must carry the logical clock instant, got {performed!r}"
        )
