"""Starting scoped work, the guards that order those refusals, and moving deadlines."""

from __future__ import annotations

from decimal import Decimal

import pytest

from test_helpers import (
    ApiErrorId,
    OTHER_BRAND_MANAGER_HEADERS,
    acknowledged_plan,
    assert_field_equals,
    assert_item_state,
    assert_ledger_contains,
    decide_extension,
    extension_resubmit_payload,
    issued_plan,
    ledger_entries,
    locked_budget,
    read_extension,
    read_item,
    read_plan,
    request_extension,
    resubmit_extension,
    run_compliance_sweep,
    set_clock,
    validate_error,
    validate_success,
)

PERMIT_JUSTIFICATION = (
    "The municipal building department has not yet issued the mechanical permit for the "
    "corridor package, and no work may lawfully begin without it."
)


@pytest.fixture
def pressured_plan_with_pending_extension(api):
    """Three life-safety items pressing on their date, and a guest-facing item asking for time."""
    scenario = issued_plan(
        api,
        [
            {
                "key": "ls1",
                "category": "LIFE_SAFETY",
                "standards_reference": "LS-1.1.1",
                "brand_estimated_cost_cents": 100000,
            },
            {
                "key": "ls2",
                "category": "LIFE_SAFETY",
                "standards_reference": "LS-1.1.2",
                "brand_estimated_cost_cents": 100000,
            },
            {
                "key": "ls3",
                "category": "LIFE_SAFETY",
                "standards_reference": "LS-1.1.3",
                "brand_estimated_cost_cents": 100000,
            },
            {
                "key": "casegoods",
                "category": "GUEST_FACING",
                "standards_reference": "GF-6.3.2",
                "brand_estimated_cost_cents": 1000000,
            },
            {
                "key": "boh",
                "category": "BACK_OF_HOUSE",
                "standards_reference": "BOH-2.2.7",
                "brand_estimated_cost_cents": 500000,
            },
        ],
        legal_name="Summit Ridge Hotels Inc",
        contact_email="development@summitridgehotels.example",
    )
    set_clock(api, "2026-09-15T00:00:00Z")
    request = request_extension(api, scenario, scenario.item_id("casegoods"), 90)
    return scenario, request


class TestExtensionGrantClamp:
    def test_the_pressure_ratio_is_measured_before_the_grant_moves_a_deadline(
        self, api, pressured_plan_with_pending_extension
    ):
        """"step 1 deliberately reads the deadlines as they stand *before* this grant." "The
        pressure ratio is the numerator divided by the denominator rounded half up to 4 decimal
        places". "The requesting item itself is counted in both figures while it sits in
        `DEFERRED_PENDING_EXTENSION`."

        Design: Difficulty/combinatorial_formula/extension_grant_cap_pinned_evaluation_order
        """
        _scenario, request = pressured_plan_with_pending_extension

        decided = decide_extension(
            api, request["id"], "APPROVE", headers=OTHER_BRAND_MANAGER_HEADERS
        )

        assert Decimal(str(decided["pressure_ratio_at_decision"])) == Decimal("0.6000"), (
            "three of five countable items fall inside the 60-day horizon, a ratio of 0.6000, "
            f"got {decided['pressure_ratio_at_decision']!r}"
        )

    def test_the_clamped_grant_records_a_partial_approval(
        self, api, pressured_plan_with_pending_extension
    ):
        """"Step 2 derives a multiplier: 0.5 when the pressure ratio is at least 0.60, and 1.0
        otherwise. Step 3 takes the item's category maximum — 30 days for `LIFE_SAFETY`, 120 days
        for `GUEST_FACING`, 180 days for `BACK_OF_HOUSE` — multiplies it by that multiplier, and
        rounds the product **down** to a whole number of days, giving the raw cap." "if it equals
        the effective request the request becomes `APPROVED`; otherwise the request becomes
        `APPROVED_PARTIAL`."

        Design: Difficulty/combinatorial_formula/extension_grant_cap_pinned_evaluation_order
        """
        _scenario, request = pressured_plan_with_pending_extension

        decided = decide_extension(
            api, request["id"], "APPROVE", headers=OTHER_BRAND_MANAGER_HEADERS
        )

        assert_field_equals(decided, "status", "APPROVED_PARTIAL", "extension request")
        assert_field_equals(decided, "granted_days", 60, "extension request")

    def test_the_grant_moves_only_the_charged_item_s_deadline(
        self, api, pressured_plan_with_pending_extension
    ):
        """"the granted days are added to the item's `extension_days_granted`, and the item's
        `deadline_date` is rewritten as its base category deadline plus the new accumulated
        `extension_days_granted`." "each returns the item `DEFERRED_PENDING_EXTENSION → SCOPED`".

        Design: Difficulty/combinatorial_formula/extension_grant_cap_pinned_evaluation_order
        """
        scenario, request = pressured_plan_with_pending_extension

        decide_extension(api, request["id"], "APPROVE", headers=OTHER_BRAND_MANAGER_HEADERS)

        charged = read_item(api, scenario.item_id("casegoods"))
        assert_field_equals(charged, "extension_days_granted", 60, "charged item")
        assert_item_state(charged, status="SCOPED", deadline_date="2027-06-27")

        untouched = read_item(api, scenario.item_id("ls1"))
        assert_item_state(untouched, status="SCOPED", deadline_date="2026-10-30")

    def test_the_plan_s_category_deadline_is_not_rewritten_by_an_item_grant(
        self, api, pressured_plan_with_pending_extension
    ):
        """"It stamps the three category deadlines from the date of `issued_at`:
        `life_safety_deadline_date` 90 calendar days out, `guest_facing_deadline_date` 270
        calendar days out, and `back_of_house_deadline_date` 450 calendar days out." Each approval
        "appends a ledger entry of type `EXTENSION_GRANTED` carrying the item's id and a
        `delta_cents` of 0".

        Design: Difficulty/combinatorial_formula/extension_grant_cap_pinned_evaluation_order
        """
        scenario, request = pressured_plan_with_pending_extension

        decide_extension(api, request["id"], "APPROVE", headers=OTHER_BRAND_MANAGER_HEADERS)

        plan = read_plan(api, scenario.plan_id)
        assert_field_equals(plan, "guest_facing_deadline_date", "2027-04-28", "plan")
        assert_field_equals(plan, "life_safety_deadline_date", "2026-10-30", "plan")

        assert_ledger_contains(
            ledger_entries(api, plan_id=scenario.plan_id),
            "EXTENSION_GRANTED",
            delta_cents=0,
            item_id=scenario.item_id("casegoods"),
        )


@pytest.fixture
def extension_under_revision(api):
    """A change-of-ownership plan whose single guest-facing item has asked for 45 more days."""
    scenario = issued_plan(
        api,
        [
            {
                "key": "package",
                "category": "GUEST_FACING",
                "standards_reference": "GF-5.5.5",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
        legal_name="Bayview Lodging Group",
        contact_email="asset@bayviewlodging.example",
        trigger_type="TRANSACTION_CHANGE_OF_OWNERSHIP",
    )
    request = request_extension(
        api,
        scenario,
        scenario.item_id("package"),
        45,
        business_justification=PERMIT_JUSTIFICATION,
    )
    return scenario, request


class TestBoundedExtensionRevisionLoop:
    def test_the_loop_cycles_three_rounds_before_it_is_spent(self, api, extension_under_revision):
        """"This is the bounded revision loop: `SUBMITTED → NEEDS_MORE_JUSTIFICATION →
        SUBMITTED`, capped at three rounds." "A successful resubmission increments `round_number`
        by one and replaces both the justification and the day count."

        Design: Difficulty/non_linear_state_machine/extension_revision_loop_bounded_by_three_rounds
        """
        scenario, request = extension_under_revision

        for _round in range(2):
            returned = decide_extension(api, request["id"], "REQUEST_MORE_JUSTIFICATION")
            assert_field_equals(
                returned, "status", "NEEDS_MORE_JUSTIFICATION", "extension request"
            )
            resubmitted = resubmit_extension(
                api,
                scenario,
                request["id"],
                requested_days=45,
                business_justification=PERMIT_JUSTIFICATION,
            )
            assert_field_equals(resubmitted, "status", "SUBMITTED", "extension request")

        final = decide_extension(api, request["id"], "REQUEST_MORE_JUSTIFICATION")

        assert_field_equals(final, "round_number", 3, "extension request")
        assert_field_equals(final, "status", "NEEDS_MORE_JUSTIFICATION", "extension request")

    def test_the_resubmission_after_the_third_round_is_refused(
        self, api, extension_under_revision
    ):
        """"the resubmission is refused unless the request is in `NEEDS_MORE_JUSTIFICATION`
        (`ERR_EXTENSION_NOT_RESUBMITTABLE`), unless `round_number` is still strictly below 3
        (`ERR_EXTENSION_ROUNDS_EXHAUSTED`, 409)".

        Design: Difficulty/non_linear_state_machine/extension_revision_loop_bounded_by_three_rounds
        """
        scenario, request = extension_under_revision
        for _round in range(2):
            decide_extension(api, request["id"], "REQUEST_MORE_JUSTIFICATION")
            resubmit_extension(
                api,
                scenario,
                request["id"],
                requested_days=45,
                business_justification=PERMIT_JUSTIFICATION,
            )
        decide_extension(api, request["id"], "REQUEST_MORE_JUSTIFICATION")

        response = api.resubmit_extension_request(
            request["id"],
            extension_resubmit_payload(
                requested_days=45, business_justification=PERMIT_JUSTIFICATION
            ),
            scenario.owner_headers,
        )

        validate_error(response, ApiErrorId.ERR_EXTENSION_ROUNDS_EXHAUSTED, 409)
        spent = read_extension(api, request["id"])
        assert_field_equals(spent, "round_number", 3, "extension request")
        assert_field_equals(spent, "status", "NEEDS_MORE_JUSTIFICATION", "extension request")
        assert_field_equals(spent, "granted_days", 0, "extension request")

    def test_the_charged_item_stays_deferred_with_its_deadline_untouched(
        self, api, extension_under_revision
    ):
        """"a decision of `REQUEST_MORE_JUSTIFICATION` alone leaves the item deferred."
        "crucially, the item's `deadline_date` does **not** change while the request is pending."

        Design: Difficulty/non_linear_state_machine/extension_revision_loop_bounded_by_three_rounds
        """
        scenario, request = extension_under_revision
        for _round in range(2):
            decide_extension(api, request["id"], "REQUEST_MORE_JUSTIFICATION")
            resubmit_extension(
                api,
                scenario,
                request["id"],
                requested_days=45,
                business_justification=PERMIT_JUSTIFICATION,
            )
        decide_extension(api, request["id"], "REQUEST_MORE_JUSTIFICATION")

        charged = read_item(api, scenario.item_id("package"))

        assert_item_state(
            charged, status="DEFERRED_PENDING_EXTENSION", deadline_date="2027-04-28"
        )
        assert_field_equals(charged, "extension_days_granted", 0, "charged item")


@pytest.fixture
def plan_with_overdue_life_safety_and_a_sequenced_item(api):
    """A sequenced guest-facing item behind both an unfinished predecessor and an overdue alarm."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "alarm",
                "category": "LIFE_SAFETY",
                "standards_reference": "LS-5.1.1",
                "brand_estimated_cost_cents": 1000000,
            },
            {
                "key": "predecessor",
                "category": "GUEST_FACING",
                "standards_reference": "GF-5.1.1",
                "brand_estimated_cost_cents": 1000000,
            },
            {
                "key": "successor",
                "category": "GUEST_FACING",
                "standards_reference": "GF-5.1.2",
                "brand_estimated_cost_cents": 1000000,
                "predecessor_key": "predecessor",
            },
        ],
        legal_name="Lakeshore Suites LLC",
        contact_email="ops@lakeshoresuites.example",
    )
    locked_budget(api, scenario, 3465000, financing_source="OWNER_EQUITY")
    set_clock(api, "2026-10-31T00:00:00Z")
    run_compliance_sweep(api, scenario.plan_id)
    return scenario


class TestItemStartGuardOrdering:
    def test_the_life_safety_precedence_check_outranks_the_predecessor_gate(
        self, api, plan_with_overdue_life_safety_and_a_sequenced_item
    ):
        """"starting a guest-facing item whose sequencing predecessor is still in progress on a
        plan that also has an overdue life-safety item breaks the safety rule in band 6 and the
        predecessor rule in band 8; the response is `ERR_LIFE_SAFETY_PRIORITY_VIOLATION` (409),
        never `ERR_PREDECESSOR_NOT_SATISFIED`."

        Design: Difficulty/priority_pair_validation_conflict/life_safety_precedence_outranks_predecessor_gate
        """
        scenario = plan_with_overdue_life_safety_and_a_sequenced_item

        response = api.start_item(scenario.item_id("successor"), scenario.owner_headers)

        validate_error(response, ApiErrorId.ERR_LIFE_SAFETY_PRIORITY_VIOLATION, 409)
        assert_field_equals(
            read_item(api, scenario.item_id("successor")), "status", "SCOPED", "successor item"
        )

    def test_the_predecessor_gate_surfaces_once_no_life_safety_item_is_overdue(
        self, api, plan_with_overdue_life_safety_and_a_sequenced_item
    ):
        """"If the item carries a `predecessor_item_id`, that predecessor's `status` must be
        `WORK_COMPLETE`, `ACCEPTED` or `REMOVED_BY_DISPUTE`, or the start is refused with
        `ERR_PREDECESSOR_NOT_SATISFIED`".

        Design: Difficulty/priority_pair_validation_conflict/life_safety_precedence_outranks_predecessor_gate
        """
        scenario = plan_with_overdue_life_safety_and_a_sequenced_item
        set_clock(api, "2026-08-02T00:00:00Z")
        run_compliance_sweep(api, scenario.plan_id)

        response = api.start_item(scenario.item_id("successor"), scenario.owner_headers)

        validate_error(response, ApiErrorId.ERR_PREDECESSOR_NOT_SATISFIED, 409)
        assert_field_equals(
            read_item(api, scenario.item_id("successor")), "status", "SCOPED", "successor item"
        )

    def test_the_sweep_turns_the_passage_of_logical_time_into_recorded_overdue_state(
        self, api, brand_manager, plan_with_overdue_life_safety_and_a_sequenced_item
    ):
        """"it re-evaluates the overdue flag on every item of the plan against the current clock,
        recomputes the plan's `overdue_item_count`". "The comparison is strict, so an item is not
        overdue on its deadline date itself — it becomes overdue on the following day."

        Design: Difficulty/priority_pair_validation_conflict/life_safety_precedence_outranks_predecessor_gate
        """
        scenario = plan_with_overdue_life_safety_and_a_sequenced_item

        assert_item_state(read_item(api, scenario.item_id("alarm")), is_overdue=True)
        assert_field_equals(read_plan(api, scenario.plan_id), "overdue_item_count", 1, "plan")

        set_clock(api, "2026-08-02T00:00:00Z")
        swept = validate_success(api.run_compliance_sweep(scenario.plan_id, brand_manager))

        assert_item_state(read_item(api, scenario.item_id("alarm")), is_overdue=False)
        assert_field_equals(swept, "overdue_item_count", 0, "plan")
        assert_field_equals(swept, "status", "OWNER_ACKNOWLEDGED", "plan")
