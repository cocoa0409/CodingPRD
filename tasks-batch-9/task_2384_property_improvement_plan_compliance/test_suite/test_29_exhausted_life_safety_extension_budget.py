"""A category relief budget spent in one grant, and the second request the brand cannot approve."""

from __future__ import annotations

from decimal import Decimal

import pytest

from test_helpers import (
    ApiErrorId,
    acknowledged_plan,
    assert_field_equals,
    assert_item_state,
    assert_ledger_contains,
    decide_extension,
    extension_decision_payload,
    ledger_entries,
    list_rows,
    read_extension,
    read_item,
    request_extension,
    validate_error,
)

_FIRST_JUSTIFICATION = (
    "The sprinkler main tie-in requires a municipal water shutdown that the utility scheduled for "
    "November."
)
_SECOND_JUSTIFICATION = (
    "The utility has now moved the water shutdown window a further two weeks into December."
)
_DENIAL_NOTE = "The category relief budget for life-safety scope is fully spent."


@pytest.fixture
def life_safety_item_with_its_relief_budget_spent(api):
    """One life-safety line whose full thirty days of category relief have already been granted."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "sprinklers",
                "category": "LIFE_SAFETY",
                "standards_reference": "LS-34.1.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
        legal_name="Kirkbanks Hotels LLC",
        contact_email="ops@kirkbanksh.example",
        property_overrides={"name": "Kirkbanks Riverside"},
    )
    first = request_extension(
        api,
        scenario,
        scenario.item_id("sprinklers"),
        30,
        business_justification=_FIRST_JUSTIFICATION,
    )
    first = decide_extension(api, first["id"], "APPROVE")
    return scenario, first


def _file_the_second_request(api, scenario):
    return request_extension(
        api,
        scenario,
        scenario.item_id("sprinklers"),
        15,
        business_justification=_SECOND_JUSTIFICATION,
    )


class TestTheCategoryBudgetIsSpentAtDecisionTime:
    def test_the_first_grant_is_full_and_consumes_the_whole_category_budget(
        self, api, life_safety_item_with_its_relief_budget_spent
    ):
        """"Step 3 takes the item's category maximum — 30 days for `LIFE_SAFETY`, 120 days for
        `GUEST_FACING`, 180 days for `BACK_OF_HOUSE` — multiplies it by that multiplier, and rounds the
        product **down** to a whole number of days, giving the raw cap." "Step 7 then commits:
        `pressure_ratio_at_decision` is stored as the ratio measured in step 1, the granted days are added
        to the item's `extension_days_granted`, and the item's `deadline_date` is rewritten as its base
        category deadline plus the new accumulated `extension_days_granted`."

        Design: Corner/errors/exhausted_life_safety_extension_budget_is_triggerable
        """
        scenario, first = life_safety_item_with_its_relief_budget_spent

        assert_field_equals(first, "status", "APPROVED", "request")
        assert_field_equals(first, "granted_days", 30, "request")
        assert Decimal(str(first["pressure_ratio_at_decision"])) == Decimal("0.0000"), (
            "no item falls inside the sixty-day pressure horizon, so the ratio is 0.0000, got "
            f"{first['pressure_ratio_at_decision']!r}"
        )
        item = read_item(api, scenario.item_id("sprinklers"))
        assert_item_state(item, status="SCOPED", deadline_date="2026-11-29")
        assert_field_equals(item, "extension_days_granted", 30, "item")
        assert_ledger_contains(
            ledger_entries(api, plan_id=scenario.plan_id),
            "EXTENSION_GRANTED",
            delta_cents=0,
            item_id=scenario.item_id("sprinklers"),
            count=1,
        )

    def test_a_second_request_may_still_be_filed_against_the_same_item(
        self, api, life_safety_item_with_its_relief_budget_spent
    ):
        """"Timing matters: an extension may be requested only while the clock date is at or before the
        item's `deadline_date`; once the item is already overdue its deadline can no longer be moved, and
        the request is refused with `ERR_EXTENSION_AFTER_DEADLINE` (409)." "A new request is created in
        `SUBMITTED` with `round_number` 1, `granted_days` 0, `pressure_ratio_at_decision` null,
        `decided_by_user_id` null and `decision_note` null."

        Design: Corner/errors/exhausted_life_safety_extension_budget_is_triggerable
        """
        scenario, _first = life_safety_item_with_its_relief_budget_spent

        second = _file_the_second_request(api, scenario)

        assert_field_equals(second, "status", "SUBMITTED", "second request")
        assert_field_equals(second, "granted_days", 0, "second request")
        assert_item_state(
            read_item(api, scenario.item_id("sprinklers")),
            status="DEFERRED_PENDING_EXTENSION",
            deadline_date="2026-11-29",
        )

    def test_the_approval_is_refused_because_no_days_remain_to_grant(
        self, api, brand_manager, life_safety_item_with_its_relief_budget_spent
    ):
        """"Step 4 computes the days remaining in the item's category budget as that same category maximum
        less the item's `extension_days_granted` accumulated so far. Step 5 takes the smallest of three
        figures: the effective request, the raw cap, and the remaining days. Step 6 branches on that
        result: if it is zero or negative the approval is refused with `ERR_EXTENSION_CAP_EXHAUSTED` (409)
        — a request whose category budget is already consumed, or whose pressure clamp leaves no room, is
        refused rather than granted zero days".

        Design: Corner/errors/exhausted_life_safety_extension_budget_is_triggerable
        """
        scenario, _first = life_safety_item_with_its_relief_budget_spent
        second = _file_the_second_request(api, scenario)

        response = api.decide_extension_request(
            second["id"], extension_decision_payload("APPROVE"), brand_manager
        )

        validate_error(response, ApiErrorId.ERR_EXTENSION_CAP_EXHAUSTED, 409)
        assert_field_equals(
            read_extension(api, second["id"]), "status", "SUBMITTED", "second request"
        )
        assert_item_state(
            read_item(api, scenario.item_id("sprinklers")), deadline_date="2026-11-29"
        )

    def test_the_same_request_may_still_be_denied(
        self, api, life_safety_item_with_its_relief_budget_spent
    ):
        """"A `DENY` moves the request `SUBMITTED → DENIED`, sets `granted_days` to 0, stores
        `pressure_ratio_at_decision`, `decided_by_user_id` and `decision_note`, and returns the item
        `DEFERRED_PENDING_EXTENSION → SCOPED` with `extension_days_granted` and `deadline_date`
        unchanged."

        Design: Corner/errors/exhausted_life_safety_extension_budget_is_triggerable
        """
        scenario, _first = life_safety_item_with_its_relief_budget_spent
        second = _file_the_second_request(api, scenario)

        denied = decide_extension(
            api, second["id"], "DENY", decision_note=_DENIAL_NOTE
        )

        assert_field_equals(denied, "status", "DENIED", "second request")
        assert_field_equals(denied, "granted_days", 0, "second request")
        assert_field_equals(denied, "decided_by_user_id", "bm-001", "second request")
        item = read_item(api, scenario.item_id("sprinklers"))
        assert_item_state(item, status="SCOPED", deadline_date="2026-11-29")
        assert_field_equals(item, "extension_days_granted", 30, "item")

    def test_two_requests_stand_on_the_item_but_only_one_grant_on_the_ledger(
        self, api, brand_manager, life_safety_item_with_its_relief_budget_spent
    ):
        """"each appends a ledger entry of type `EXTENSION_GRANTED` carrying the item's id and a
        `delta_cents` of 0". "`APPROVED`, `APPROVED_PARTIAL` and `DENIED` are the terminal request states;
        a decision of `REQUEST_MORE_JUSTIFICATION` alone leaves the item deferred."

        Design: Corner/errors/exhausted_life_safety_extension_budget_is_triggerable
        """
        scenario, _first = life_safety_item_with_its_relief_budget_spent
        second = _file_the_second_request(api, scenario)
        validate_error(
            api.decide_extension_request(
                second["id"], extension_decision_payload("APPROVE"), brand_manager
            ),
            ApiErrorId.ERR_EXTENSION_CAP_EXHAUSTED,
            409,
        )
        decide_extension(api, second["id"], "DENY", decision_note=_DENIAL_NOTE)

        _rows, meta = list_rows(
            api, "list_extension_requests", item_id=scenario.item_id("sprinklers")
        )

        assert meta["total_count"] == 2, f"both filings survive as rows, got {meta}"
        assert_ledger_contains(
            ledger_entries(api, plan_id=scenario.plan_id), "EXTENSION_GRANTED", count=1
        )
