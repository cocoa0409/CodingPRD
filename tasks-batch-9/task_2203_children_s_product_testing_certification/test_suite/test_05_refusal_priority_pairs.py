"""Requests that break two rules at once, where only the earlier rank may answer."""

from test_helpers import ApiErrorId, factories, fixtures as fx, validate_error, validate_success
from test_helpers.test_users import ADMIN_HEADERS, COORDINATOR_HEADERS


LEAD_RULE = {
    "hazard_class": "LEAD_CONTENT",
    "severity_weight": 9,
    "limit_value": 100,
    "limit_unit": "PPM",
    "base_method_fee_cents": 18700,
}

FLAT_CATEGORY = {"durable_infant_product": False, "sampling_floor_units": 1}

BOOKING_WINDOW = {
    "window_start": "2026-08-10T00:00:00Z",
    "window_end": "2026-08-12T00:00:00Z",
}


def _unaccredited_draft_plan_env(api):
    """A scoped product whose plan is still DRAFT at a laboratory holding no accreditation."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    library = fx.regulatory_env(api, [dict(LEAD_RULE)], dict(FLAT_CATEGORY))
    rule = library["rules"][0]
    laboratory = fx.create_laboratory(api, independence_class="INDEPENDENT")
    fx.attest(api, laboratory["id"], "2027-12-31T00:00:00Z")
    supplier = fx.create_supplier(api)
    product = fx.create_product(
        api, library["category"]["id"], projected_annual_units=1000
    )
    fx.add_part(api, product["id"], supplier["id"], material_class="PAINTED_COATING")
    product = fx.submit_for_certification(api, product["id"], "FULL_PRODUCT_TEST")
    assert product["required_rule_ids"] == [rule["id"]]
    plan = fx.create_plan(api, product["id"], plan_type="INITIAL")
    assert plan["plan_state"] == "DRAFT"

    payload = factories.test_order_payload(
        product["id"], plan["id"], laboratory["id"], rule["id"],
        sample_count=1, **BOOKING_WINDOW,
    )
    return {
        "rule": rule,
        "laboratory": laboratory,
        "product": product,
        "plan": plan,
        "payload": payload,
    }


class TestPlanStateOutranksMethodAccreditation:
    """A draft plan answers before an unaccredited method gets a say."""

    def test_draft_plan_answers_before_the_missing_method_accreditation(self, api):
        """PRD 2.11: "When a single request violates more than one rule, the response is
        decided by the **first** violated rule in the strict ordering below, and no later
        rule may mask an earlier one." and "Sampling plan state — `DRAFT` for activation,
        either `ACTIVE` or `RESAMPLE_DUE` for periodic review, and either `ACTIVE` or
        `RESAMPLE_DUE` to accept a new test order → `ERR_PLAN_STATE_INVALID` (409)."

        Design: Difficulty/priority_pair_validation_conflict/priority_conflict_state_plan_not_active_outranks_business_safety_lab_not_accredited
        """
        env = _unaccredited_draft_plan_env(api)
        # The accreditation guard also holds here, and must stay silent.
        validate_error(
            api.create_test_order(env["payload"], headers=COORDINATOR_HEADERS),
            ApiErrorId.PLAN_STATE_INVALID.value,
            409,
        )
        assert fx.get_plan(api, env["plan"]["id"])["plan_state"] == "DRAFT"
        assert fx.list_orders_for_product(api, env["product"]["id"]) == []

    def test_missing_accreditation_answers_once_the_plan_is_active(self, api):
        """PRD 2.11: "Method accreditation — exactly one `ACCREDITED` accreditation row
        covers the laboratory, the rule's test method and the logical clock →
        `ERR_LAB_METHOD_NOT_ACCREDITED` (422)."

        Design: Difficulty/priority_pair_validation_conflict/priority_conflict_state_plan_not_active_outranks_business_safety_lab_not_accredited
        """
        env = _unaccredited_draft_plan_env(api)
        activated = fx.activate_plan(api, env["plan"]["id"])
        assert activated["plan_state"] == "ACTIVE"

        validate_error(
            api.create_test_order(env["payload"], headers=COORDINATOR_HEADERS),
            ApiErrorId.LAB_METHOD_NOT_ACCREDITED.value,
            422,
        )
        assert fx.list_orders_for_product(api, env["product"]["id"]) == []

    def test_identical_request_is_booked_once_both_conditions_are_satisfied(self, api):
        """PRD 3.6: "On creation the order's `order_state` is `SCHEDULED`, its
        `ordered_by_user_id` is the acting `X-User-ID`, `is_retest` is false and
        `retest_case_id` is null; `measured_value`, `result`, `reported_at` and
        `reported_by_user_id` are all null."

        Design: Difficulty/priority_pair_validation_conflict/priority_conflict_state_plan_not_active_outranks_business_safety_lab_not_accredited
        """
        env = _unaccredited_draft_plan_env(api)
        api.create_test_order(env["payload"], headers=COORDINATOR_HEADERS)
        fx.activate_plan(api, env["plan"]["id"])
        api.create_test_order(env["payload"], headers=COORDINATOR_HEADERS)

        validate_success(
            api.create_accreditation(
                env["laboratory"]["id"],
                factories.accreditation_payload(
                    env["rule"]["id"],
                    valid_from="2026-01-01T00:00:00Z",
                    valid_through="2027-01-01T00:00:00Z",
                    fee_surcharge_basis_points=0,
                ),
                headers=ADMIN_HEADERS,
            ),
            201,
        )
        order = validate_success(
            api.create_test_order(env["payload"], headers=COORDINATOR_HEADERS), 201
        )

        assert order["order_state"] == "SCHEDULED"
        assert order["line_fee_cents"] == 18700
        assert order["is_retest"] is False
        assert order["retest_case_id"] is None
        assert order["measured_value"] is None
        assert order["result"] is None
        assert order["reported_at"] is None

        orders = fx.list_orders_for_product(api, env["product"]["id"])
        assert len(orders) == 1


OCCUPIED_WINDOW = {
    "window_start": "2026-08-10T00:00:00Z",
    "window_end": "2026-08-20T00:00:00Z",
}
INSIDE_WINDOW = {
    "window_start": "2026-08-12T00:00:00Z",
    "window_end": "2026-08-15T00:00:00Z",
}
ADJACENT_WINDOW = {
    "window_start": "2026-08-20T00:00:00Z",
    "window_end": "2026-08-25T00:00:00Z",
}


def _single_slot_env(api):
    """One laboratory slot occupied, and one authorised sample unit left over."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    env = fx.booking_env(
        api,
        rule_specs=[dict(LEAD_RULE)],
        category=dict(FLAT_CATEGORY),
        product={"projected_annual_units": 100},
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 1},
        accreditation_overrides=[{"fee_surcharge_basis_points": 0}],
        plan_overrides={"plan_type": "INITIAL"},
    )
    assert env["plan"]["units_authorized"] == 4
    first = fx.book_order(
        api,
        env["product"]["id"],
        env["plan"]["id"],
        env["laboratory"]["id"],
        env["rules"][0]["id"],
        sample_count=3,
        **OCCUPIED_WINDOW,
    )
    plan = fx.get_plan(api, env["plan"]["id"])
    assert plan["units_committed"] == 3
    assert plan["units_available"] == 1
    env["first_order"] = first
    return env


def _candidate(env, sample_count, window):
    return factories.test_order_payload(
        env["product"]["id"],
        env["plan"]["id"],
        env["laboratory"]["id"],
        env["rules"][0]["id"],
        sample_count=sample_count,
        **window,
    )


class TestSlotCapacityOutranksSampleUnits:
    """An overbooked slot answers before an overdrawn unit ledger."""

    def test_slot_capacity_answers_before_the_exhausted_sample_units(self, api):
        """PRD 2.11: "Laboratory slot capacity — peak concurrency of half-open testing
        windows at the laboratory does not exceed its `concurrent_slot_capacity` →
        `ERR_LAB_SLOT_CAPACITY_EXCEEDED` (409)." and "no later rule may mask an earlier
        one."

        Design: Difficulty/priority_pair_validation_conflict/priority_conflict_business_temporal_lab_capacity_outranks_business_constraint_sample_units_exhausted
        """
        env = _single_slot_env(api)
        # The unit ledger is also short by one here, and must stay silent.
        validate_error(
            api.create_test_order(
                _candidate(env, 2, INSIDE_WINDOW), headers=COORDINATOR_HEADERS
            ),
            ApiErrorId.LAB_SLOT_CAPACITY_EXCEEDED.value,
            409,
        )
        plan = fx.get_plan(api, env["plan"]["id"])
        assert plan["units_committed"] == 3
        assert plan["units_available"] == 1

    def test_exhausted_sample_units_answer_for_a_window_that_only_touches_the_other_end(
        self, api
    ):
        """PRD 3.6: "The window is **half-open**: it includes `window_start` and excludes
        `window_end`." PRD 2.11: "Sample units available — the requested `sample_count`
        does not exceed the plan's `units_available` → `ERR_SAMPLE_UNITS_EXHAUSTED`
        (422)."

        Design: Difficulty/priority_pair_validation_conflict/priority_conflict_business_temporal_lab_capacity_outranks_business_constraint_sample_units_exhausted
        """
        env = _single_slot_env(api)
        validate_error(
            api.create_test_order(
                _candidate(env, 2, ADJACENT_WINDOW), headers=COORDINATOR_HEADERS
            ),
            ApiErrorId.SAMPLE_UNITS_EXHAUSTED.value,
            422,
        )
        assert len(fx.list_orders_for_product(api, env["product"]["id"])) == 1

    def test_a_fitting_count_on_the_adjacent_window_is_booked(self, api):
        """PRD 2.8: "The invariant is that `units_committed` plus `units_available`
        equals `units_authorized` at all times, and it must hold identically before an
        order is booked and after that same order is cancelled — cancellation returns
        exactly the units the booking took, with no drift."

        Design: Difficulty/priority_pair_validation_conflict/priority_conflict_business_temporal_lab_capacity_outranks_business_constraint_sample_units_exhausted
        """
        env = _single_slot_env(api)
        api.create_test_order(_candidate(env, 2, INSIDE_WINDOW), headers=COORDINATOR_HEADERS)
        api.create_test_order(
            _candidate(env, 2, ADJACENT_WINDOW), headers=COORDINATOR_HEADERS
        )
        order = validate_success(
            api.create_test_order(
                _candidate(env, 1, ADJACENT_WINDOW), headers=COORDINATOR_HEADERS
            ),
            201,
        )
        assert order["order_state"] == "SCHEDULED"
        assert order["sample_count"] == 1

        plan = fx.get_plan(api, env["plan"]["id"])
        assert plan["units_authorized"] == 4
        assert plan["units_committed"] == 4
        assert plan["units_available"] == 0
        assert len(fx.list_orders_for_product(api, env["product"]["id"])) == 2
