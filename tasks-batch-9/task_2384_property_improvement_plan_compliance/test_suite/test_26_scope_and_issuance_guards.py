"""Eight scoping-side guards, from an empty plan to a phase number already spoken for."""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    acknowledged_plan,
    assert_field_equals,
    assert_item_state,
    assert_plan_dimensions,
    bootstrap_portfolio,
    current_plan_version,
    dispute_payload,
    extension_request_payload,
    file_dispute,
    issue_plan,
    item_payload,
    item_revision_payload,
    list_rows,
    read_item,
    read_plan,
    renovation_phase_payload,
    request_extension,
    schedule_phase,
    scope_plan,
    validate_error,
)

_FIRST_JUSTIFICATION = (
    "The corridor carpet mill has quoted a fourteen-week lead time from the approved strike-off."
)
_SECOND_JUSTIFICATION = (
    "A second justification filed while the first request is still awaiting a brand decision."
)


@pytest.fixture
def a_draft_plan_with_nothing_scoped(api):
    """A plan created against a live property and never given a single line of scope."""
    portfolio = bootstrap_portfolio(
        api, "Halloway Hotels LLC", "ops@hallowayh.example", name="Halloway Corn Mill"
    )
    return scope_plan(api, portfolio, ())


@pytest.fixture
def issued_plan_a_beside_draft_plan_b(api):
    """One issued plan and one still-draft relicensing plan on the same house."""
    portfolio = bootstrap_portfolio(
        api, "Halloway Hotels LLC", "ops@hallowayh.example", name="Halloway Corn Mill"
    )
    plan_a = scope_plan(
        api,
        portfolio,
        [
            {
                "key": "corridors",
                "category": "GUEST_FACING",
                "standards_reference": "GF-31.1.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
    )
    plan_a = issue_plan(api, plan_a)
    plan_b = scope_plan(
        api,
        portfolio,
        [
            {
                "key": "laundry",
                "category": "BACK_OF_HOUSE",
                "standards_reference": "BOH-31.2.2",
                "brand_estimated_cost_cents": 500000,
            }
        ],
        trigger_type="RELICENSING",
    )
    return plan_a, plan_b


@pytest.fixture
def acknowledged_plan_open_to_relief_and_contest(api):
    """An acknowledged plan whose single guest-facing line can be deferred and contested."""
    return acknowledged_plan(
        api,
        [
            {
                "key": "corridors",
                "category": "GUEST_FACING",
                "standards_reference": "GF-31.1.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
        legal_name="Halloway Hotels LLC",
        contact_email="ops@hallowayh.example",
        property_overrides={"name": "Halloway Corn Mill"},
    )


class TestIssuanceAndScopeEditsGuardEachOther:
    def test_a_plan_with_no_scope_cannot_be_issued(
        self, api, brand_manager, a_draft_plan_with_nothing_scoped
    ):
        """"Issuing the plan is the brand's act of freezing the scope and starting the clock, and it is
        refused unless the plan is `DRAFT` (`ERR_PLAN_NOT_ISSUABLE`), unless at least one item of the plan
        is in `SCOPED` (`ERR_PLAN_HAS_NO_ITEMS`), and unless the property's franchise agreement is not
        terminated."

        Design: Corner/errors/scope_and_issuance_guards_are_triggerable
        """
        scenario = a_draft_plan_with_nothing_scoped

        response = api.issue_plan(scenario.plan_id, brand_manager)

        validate_error(response, ApiErrorId.ERR_PLAN_HAS_NO_ITEMS, 409)
        plan = read_plan(api, scenario.plan_id)
        assert_plan_dimensions(plan, status="DRAFT")
        assert plan["issued_at"] is None, f"a refused issuance starts no clock, got {plan!r}"
        assert_field_equals(plan, "scope_item_count", 0, "plan")

    def test_scope_is_frozen_the_moment_the_plan_is_issued(
        self, api, brand_manager, issued_plan_a_beside_draft_plan_b
    ):
        """"Scope is then filled in item by item, and only while the plan is `DRAFT` — an attempt to add
        or revise an item after issuance is refused with `ERR_PLAN_NOT_DRAFT`."

        Design: Corner/errors/scope_and_issuance_guards_are_triggerable
        """
        plan_a, _plan_b = issued_plan_a_beside_draft_plan_b

        response = api.patch_item(
            plan_a.item_id("corridors"),
            item_revision_payload(
                current_plan_version(api, plan_a.plan_id), brand_estimated_cost_cents=1500000
            ),
            brand_manager,
        )

        validate_error(response, ApiErrorId.ERR_PLAN_NOT_DRAFT, 409)
        assert_field_equals(
            read_item(api, plan_a.item_id("corridors")),
            "brand_estimated_cost_cents",
            1000000,
            "issued item",
        )


class TestTheSequencingEdgeMayNotLeaveItsPlanOrCloseOnItself:
    def test_a_predecessor_from_another_plan_is_refused(
        self, api, brand_manager, issued_plan_a_beside_draft_plan_b
    ):
        """"A supplied `predecessor_item_id` must reference an item of the *same* plan
        (`ERR_PREDECESSOR_PLAN_MISMATCH`, 422), and must neither point at the item itself nor close a
        cycle anywhere in the sequencing chain (`ERR_PREDECESSOR_CYCLE`, 422)."

        Design: Corner/errors/scope_and_issuance_guards_are_triggerable
        """
        plan_a, plan_b = issued_plan_a_beside_draft_plan_b

        response = api.create_item(
            item_payload(
                plan_b.plan_id,
                category="BACK_OF_HOUSE",
                standards_reference="BOH-31.2.1",
                brand_estimated_cost_cents=500000,
                predecessor_item_id=plan_a.item_id("corridors"),
            ),
            brand_manager,
        )

        validate_error(response, ApiErrorId.ERR_PREDECESSOR_PLAN_MISMATCH, 422)
        assert_field_equals(read_plan(api, plan_b.plan_id), "scope_item_count", 1, "plan B")

    def test_an_item_may_not_be_its_own_predecessor(
        self, api, brand_manager, issued_plan_a_beside_draft_plan_b
    ):
        """"and must neither point at the item itself nor close a cycle anywhere in the sequencing chain
        (`ERR_PREDECESSOR_CYCLE`, 422)." "The same room-impact agreement rule, the same-plan predecessor
        rule and the cycle rule are all re-checked on revision."

        Design: Corner/errors/scope_and_issuance_guards_are_triggerable
        """
        _plan_a, plan_b = issued_plan_a_beside_draft_plan_b
        item_b = plan_b.item_id("laundry")

        response = api.patch_item(
            item_b,
            item_revision_payload(
                current_plan_version(api, plan_b.plan_id), predecessor_item_id=item_b
            ),
            brand_manager,
        )

        validate_error(response, ApiErrorId.ERR_PREDECESSOR_CYCLE, 422)
        read_back = read_item(api, item_b)
        assert read_back["predecessor_item_id"] is None, (
            f"a refused revision leaves the sequencing edge unset, got {read_back!r}"
        )

    def test_an_item_of_a_draft_plan_cannot_be_started(
        self, api, issued_plan_a_beside_draft_plan_b
    ):
        """"The governing plan's `status` must be `OWNER_ACKNOWLEDGED` or `IN_EXECUTION`, or
        `ERR_PLAN_NOT_IN_EXECUTION_WINDOW`."

        Design: Corner/errors/scope_and_issuance_guards_are_triggerable
        """
        _plan_a, plan_b = issued_plan_a_beside_draft_plan_b

        response = api.start_item(plan_b.item_id("laundry"), plan_b.owner_headers)

        validate_error(response, ApiErrorId.ERR_PLAN_NOT_IN_EXECUTION_WINDOW, 409)
        assert_item_state(read_item(api, plan_b.item_id("laundry")), status="SCOPED")
        assert_plan_dimensions(read_plan(api, plan_b.plan_id), status="DRAFT")


class TestOnlyOneReliefContestAndPhaseNumberAtATime:
    def test_a_second_relief_request_on_the_same_item_is_refused(
        self, api, acknowledged_plan_open_to_relief_and_contest
    ):
        """"Only one request may be in flight per item — if the item already has a request in `SUBMITTED`
        or `NEEDS_MORE_JUSTIFICATION`, the new one is refused with `ERR_EXTENSION_ALREADY_PENDING` (409)."

        Design: Corner/errors/scope_and_issuance_guards_are_triggerable
        """
        scenario = acknowledged_plan_open_to_relief_and_contest
        first = request_extension(
            api,
            scenario,
            scenario.item_id("corridors"),
            30,
            business_justification=_FIRST_JUSTIFICATION,
        )

        response = api.create_extension_request(
            extension_request_payload(
                scenario.item_id("corridors"),
                20,
                business_justification=_SECOND_JUSTIFICATION,
            ),
            scenario.owner_headers,
        )

        validate_error(response, ApiErrorId.ERR_EXTENSION_ALREADY_PENDING, 409)
        rows, meta = list_rows(
            api, "list_extension_requests", item_id=scenario.item_id("corridors")
        )
        assert meta["total_count"] == 1, f"only the first request may exist, got {meta}"
        assert rows[0]["id"] == first["id"], (
            f"the surviving request is the first one filed, got {rows[0]!r}"
        )

    def test_a_second_live_dispute_on_the_same_item_is_refused(
        self, api, acknowledged_plan_open_to_relief_and_contest
    ):
        """"Only one dispute may be live per item: if another dispute on the same `item_id` is still in
        `FILED`, the filing is refused with `ERR_DISPUTE_ALREADY_OPEN` (409)."

        Design: Corner/errors/scope_and_issuance_guards_are_triggerable
        """
        scenario = acknowledged_plan_open_to_relief_and_contest
        first = file_dispute(
            api,
            scenario,
            scenario.item_id("corridors"),
            claimed_cost_cents=700000,
            dispute_basis="COST_ESTIMATE",
        )

        response = api.create_dispute(
            dispute_payload(
                scenario.plan_id,
                scenario.item_id("corridors"),
                650000,
                "SCOPE_REASONABLENESS",
            ),
            scenario.owner_headers,
        )

        validate_error(response, ApiErrorId.ERR_DISPUTE_ALREADY_OPEN, 409)
        assert_field_equals(first, "status", "FILED", "first dispute")
        _rows, meta = list_rows(api, "list_disputes", plan_id=scenario.plan_id)
        assert meta["total_count"] == 1, f"only the first contest may exist, got {meta}"
        assert_plan_dimensions(read_plan(api, scenario.plan_id), dispute_state="DISPUTE_OPEN")

    def test_a_phase_number_is_unique_within_its_plan(
        self, api, acknowledged_plan_open_to_relief_and_contest
    ):
        """"The `phase_number` must be unique among the phases of the same plan whose `status` is not
        `CANCELLED` — a cancelled phase releases its number — and a collision is
        `ERR_PHASE_NUMBER_DUPLICATE` (409)."

        Design: Corner/errors/scope_and_issuance_guards_are_triggerable
        """
        scenario = acknowledged_plan_open_to_relief_and_contest
        first = schedule_phase(
            api,
            scenario,
            phase_number=1,
            start_date="2026-09-01",
            end_date="2026-09-10",
            rooms_out_of_service=10,
        )

        response = api.create_renovation_phase(
            renovation_phase_payload(
                scenario.plan_id,
                phase_number=1,
                start_date="2026-11-01",
                end_date="2026-11-10",
                rooms_out_of_service=10,
            ),
            scenario.owner_headers,
        )

        validate_error(response, ApiErrorId.ERR_PHASE_NUMBER_DUPLICATE, 409)
        rows, meta = list_rows(api, "list_renovation_phases", plan_id=scenario.plan_id)
        assert meta["total_count"] == 1, f"only phase one may exist, got {meta}"
        assert rows[0]["id"] == first["id"], (
            f"the surviving phase is the first one scheduled, got {rows[0]!r}"
        )

    def test_the_refusals_leave_the_two_plan_dimensions_where_they_were(
        self, api, acknowledged_plan_open_to_relief_and_contest
    ):
        """"The plan's `dispute_state` moves to `DISPUTE_OPEN` while its `status` is left completely
        untouched." "Creating it also moves the charged item `SCOPED → DEFERRED_PENDING_EXTENSION` and
        increments the item's `version`".

        Design: Corner/errors/scope_and_issuance_guards_are_triggerable
        """
        scenario = acknowledged_plan_open_to_relief_and_contest
        request_extension(
            api,
            scenario,
            scenario.item_id("corridors"),
            30,
            business_justification=_FIRST_JUSTIFICATION,
        )
        file_dispute(
            api,
            scenario,
            scenario.item_id("corridors"),
            claimed_cost_cents=700000,
            dispute_basis="COST_ESTIMATE",
        )

        plan = read_plan(api, scenario.plan_id)

        assert_plan_dimensions(
            plan, status="OWNER_ACKNOWLEDGED", dispute_state="DISPUTE_OPEN"
        )
        assert_field_equals(plan, "scope_item_count", 1, "plan")
        assert_item_state(
            read_item(api, scenario.item_id("corridors")),
            status="DEFERRED_PENDING_EXTENSION",
        )
