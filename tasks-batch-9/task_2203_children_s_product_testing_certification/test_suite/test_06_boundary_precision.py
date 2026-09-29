"""Values sitting exactly on a limit, a due instant and a quarantine buffer."""

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import COORDINATOR_HEADERS, make_supplier_user_headers


FLAT_CATEGORY = {"durable_infant_product": False, "sampling_floor_units": 1}

LIMIT_100_LEAD_RULE = {
    "hazard_class": "LEAD_CONTENT",
    "severity_weight": 9,
    "limit_value": 100,
    "limit_unit": "PPM",
    "limit_comparator": "AT_OR_BELOW",
    "base_method_fee_cents": 18700,
}

REPORT_WINDOWS = [
    ("2026-08-02T00:00:00Z", "2026-08-03T00:00:00Z"),
    ("2026-08-04T00:00:00Z", "2026-08-05T00:00:00Z"),
    ("2026-08-06T00:00:00Z", "2026-08-07T00:00:00Z"),
]


def _three_started_orders_env(api):
    """Three single-sample orders in testing against an inclusive limit of 100 PPM."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    env = fx.booking_env(
        api,
        rule_specs=[dict(LIMIT_100_LEAD_RULE)],
        category=dict(FLAT_CATEGORY),
        product={"projected_annual_units": 6000},
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 4},
        plan_overrides={"plan_type": "INITIAL"},
    )
    assert env["plan"]["units_authorized"] == 6
    orders = []
    for window_start, window_end in REPORT_WINDOWS:
        order = fx.book_order(
            api,
            env["product"]["id"],
            env["plan"]["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
            sample_count=1,
            window_start=window_start,
            window_end=window_end,
        )
        fx.start_order(api, order["id"], env["laboratory"]["id"])
        orders.append(order)
    env["below"], env["at_limit"], env["above"] = orders
    return env


class TestMeasuredValueAgainstAnInclusiveLimit:
    """99, 100 and 101 PPM against a limit of 100 PPM."""

    def test_a_value_exactly_at_the_limit_passes_and_one_unit_above_fails(self, api):
        """PRD 3.6: "under `AT_OR_BELOW` the result is `PASS` when the measured value is
        less than or equal to the limit, and `FAIL` otherwise" and "The comparison is
        exact, with no rounding and no tolerance, and a measured value exactly equal to
        `limit_value` passes under **both** comparators."

        Design: Difficulty/boundary_precision_check/boundary_measured_concentration_exactly_at_limit_value_passes_one_unit_above_fails
        """
        env = _three_started_orders_env(api)
        lab_id = env["laboratory"]["id"]

        below = fx.report(api, env["below"]["id"], lab_id, 99)
        assert below["result"] == "PASS"
        assert below["order_state"] == "REPORTED_PASS"

        at_limit = fx.report(api, env["at_limit"]["id"], lab_id, 100)
        assert at_limit["result"] == "PASS"
        assert at_limit["result"] != "FAIL"
        assert at_limit["order_state"] == "REPORTED_PASS"

        above = fx.report(api, env["above"]["id"], lab_id, 101)
        assert above["result"] == "FAIL"
        assert above["order_state"] == "REPORTED_FAIL"

    def test_only_the_value_above_the_limit_opens_a_noncompliance_case(self, api):
        """PRD 3.6: "Hop one: when `is_retest` is false, a noncompliance case is opened
        in `OPEN` with its `product_id`, `triggering_test_order_id` and `failed_rule_id`
        copied from this order and its `opened_by_user_id` set to the reporting
        `X-User-ID`; when `is_retest` is true, no new case is created and instead the
        servicing case advances `RETEST_ORDERED → RETEST_FAILED` with
        `active_retest_order_id` cleared to null."

        Design: Difficulty/boundary_precision_check/boundary_measured_concentration_exactly_at_limit_value_passes_one_unit_above_fails
        """
        env = _three_started_orders_env(api)
        lab_id = env["laboratory"]["id"]
        fx.report(api, env["below"]["id"], lab_id, 99)
        fx.report(api, env["at_limit"]["id"], lab_id, 100)
        fx.report(api, env["above"]["id"], lab_id, 101)

        case = fx.sole_case_for_product(api, env["product"]["id"])
        assert case["triggering_test_order_id"] == env["above"]["id"]
        assert case["case_state"] == "OPEN"

        _, meta = validate_paginated(
            api.list_cases(
                params={"triggering_test_order_id": env["at_limit"]["id"]},
                headers=COORDINATOR_HEADERS,
            )
        )
        assert meta["total_count"] == 0


MONTH_END_ACTIVATION = "2026-08-31T00:00:00Z"


def _month_end_plan_env(api):
    """An INITIAL plan verified on the 31st whose strictest interval is six months."""
    fx.set_clock(api, MONTH_END_ACTIVATION)
    env = fx.scoped_product_env(
        api,
        evidence_path="FULL_PRODUCT_TEST",
        rule_specs=[
            dict(LIMIT_100_LEAD_RULE, periodic_interval_months=12),
            {
                "hazard_class": "PHTHALATES",
                "severity_weight": 3,
                "periodic_interval_months": 6,
                "limit_value": 1000,
                "limit_unit": "PPM",
                "base_method_fee_cents": 18700,
            },
        ],
        category=dict(FLAT_CATEGORY),
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 4},
    )
    assert len(env["product"]["required_rule_ids"]) == 2
    plan = fx.create_plan(api, env["product"]["id"], plan_type="INITIAL", resample_grace_days=30)
    env["plan"] = fx.activate_plan(api, plan["id"])
    return env


class TestPeriodicDueInstantClamping:
    """A due date that lands on a day February does not have."""

    def test_due_instant_clamps_the_source_day_to_the_last_day_of_the_target_month(self, api):
        """PRD 3.5: "Otherwise, add that number of calendar months to the plan's
        `last_verified_at`, clamping the day of month to the last day of the target month
        where the source day does not exist there, and preserving the time of day
        exactly. All arithmetic is calendar-month arithmetic on the UTC instant — no
        interval is ever expressed in days."

        Design: Difficulty/boundary_precision_check/boundary_periodic_due_instant_with_month_end_day_clamping_is_due_at_equality
        """
        env = _month_end_plan_env(api)
        plan = env["plan"]

        assert plan["last_verified_at"] == MONTH_END_ACTIVATION
        assert plan["activated_at"] == MONTH_END_ACTIVATION
        assert plan["periodic_due_at"] == "2027-02-28T00:00:00Z"
        # Neither 183-day arithmetic nor a rollover into March.
        assert plan["periodic_due_at"] != "2027-03-02T00:00:00Z"
        assert plan["periodic_due_at"] != "2027-03-03T00:00:00Z"

    def test_review_is_refused_a_day_early_and_accepted_at_exact_equality(self, api):
        """PRD 3.5: "Running a **periodic review** on an `ACTIVE` plan requires that the
        logical clock be at or after `periodic_due_at`; an instant exactly equal to it is
        due, and an instant strictly before it is refused with
        `ERR_PERIODIC_REVIEW_NOT_DUE`."

        Design: Difficulty/boundary_precision_check/boundary_periodic_due_instant_with_month_end_day_clamping_is_due_at_equality
        """
        env = _month_end_plan_env(api)
        plan_id = env["plan"]["id"]

        fx.set_clock(api, "2027-02-27T00:00:00Z")
        validate_error(
            api.periodic_review(plan_id, headers=COORDINATOR_HEADERS),
            ApiErrorId.PERIODIC_REVIEW_NOT_DUE.value,
            409,
        )
        assert fx.get_plan(api, plan_id)["plan_state"] == "ACTIVE"

        fx.set_clock(api, "2027-02-28T00:00:00Z")
        reviewed = fx.periodic_review(api, plan_id)
        assert reviewed["plan_state"] == "RESAMPLE_DUE"
        assert reviewed["resample_trigger"] == "PERIODIC_INTERVAL"

    def test_lapse_needs_the_clock_strictly_past_the_grace_period(self, api):
        """PRD 3.5: "Running the same review against a plan already in `RESAMPLE_DUE` is
        how a lapse is recognised: once the logical clock is strictly past
        `periodic_due_at` plus the plan's `resample_grace_days` days, the plan moves
        `RESAMPLE_DUE → LAPSED` and the owning product's `compliance_posture` is set to
        `SUSPENDED`, with both versions incremented by 1."

        Design: Difficulty/boundary_precision_check/boundary_periodic_due_instant_with_month_end_day_clamping_is_due_at_equality
        """
        env = _month_end_plan_env(api)
        plan_id = env["plan"]["id"]
        fx.set_clock(api, "2027-02-28T00:00:00Z")
        fx.periodic_review(api, plan_id)

        # 2027-03-30 is the due instant plus exactly 30 days, so the grace has not
        # yet been passed and the plan cannot have lapsed.
        fx.set_clock(api, "2027-03-30T00:00:00Z")
        api.periodic_review(plan_id, headers=COORDINATOR_HEADERS)
        assert fx.get_plan(api, plan_id)["plan_state"] != "LAPSED"

        fx.set_clock(api, "2027-03-31T00:00:00Z")
        lapsed = fx.periodic_review(api, plan_id)
        assert lapsed["plan_state"] == "LAPSED"

    def test_a_lapsed_plan_suspends_the_posture_with_no_case_in_sight(self, api):
        """PRD 3.3: "Otherwise, a product with at least one sampling plan in `LAPSED` is
        `SUSPENDED`."

        Design: Difficulty/boundary_precision_check/boundary_periodic_due_instant_with_month_end_day_clamping_is_due_at_equality
        """
        env = _month_end_plan_env(api)
        plan_id = env["plan"]["id"]
        fx.set_clock(api, "2027-02-28T00:00:00Z")
        fx.periodic_review(api, plan_id)
        fx.set_clock(api, "2027-03-31T00:00:00Z")
        fx.periodic_review(api, plan_id)

        summary = fx.get_summary(api, env["product"]["id"])
        assert summary["compliance_posture"] == "SUSPENDED"
        assert summary["open_case_count"] == 0
        assert fx.list_cases_for_product(api, env["product"]["id"]) == []


FIRST_COVERAGE = {
    "coverage_from": "2026-01-01T00:00:00Z",
    "coverage_through": "2026-03-31T00:00:00Z",
}
CANDIDATE_THROUGH = "2026-06-30T00:00:00Z"


def _covered_part_env(api):
    """A reliance part already carrying one certificate covering January to March."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    env = fx.scoped_product_env(
        api,
        evidence_path="COMPONENT_RELIANCE",
        rule_specs=[dict(LIMIT_100_LEAD_RULE, component_reliance_allowed=True)],
        category=dict(FLAT_CATEGORY),
        supplier={"reliance_agreement_state": "ON_FILE"},
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 4},
    )
    first = fx.submit_part_certificate(
        api,
        env["parts"][0]["id"],
        env["supplier"]["id"],
        env["laboratory"]["id"],
        env["rules"][0]["id"],
        measured_value=40,
        **FIRST_COVERAGE,
    )
    assert first["reliance_state"] == "SUBMITTED"
    env["first_certificate"] = first
    return env


def _candidate_submission(api, env, coverage_from):
    return api.submit_part_certificate(
        env["parts"][0]["id"],
        factories.part_certificate_payload(
            env["laboratory"]["id"],
            env["rules"][0]["id"],
            measured_value=40,
            coverage_from=coverage_from,
            coverage_through=CANDIDATE_THROUGH,
        ),
        headers=make_supplier_user_headers(env["supplier"]["id"]),
    )


class TestCoverageQuarantineBuffer:
    """A seven-day gap collides where an eight-day gap clears."""

    def test_a_gap_of_exactly_the_buffer_collides_and_one_day_more_clears(self, api):
        """PRD 3.5: "A candidate collides with such an existing certificate when the
        candidate's `coverage_from` is at or before the existing `coverage_through`
        extended forward by seven days, **and** the existing `coverage_from` pulled back
        by seven days is at or before the candidate's `coverage_through`."

        Design: Difficulty/boundary_precision_check/boundary_component_coverage_quarantine_buffer_seven_day_gap_collides_eight_day_gap_clears
        """
        env = _covered_part_env(api)

        validate_error(
            _candidate_submission(api, env, "2026-04-07T00:00:00Z"),
            ApiErrorId.COMPONENT_COVERAGE_OVERLAP.value,
            409,
        )
        accepted = validate_success(
            _candidate_submission(api, env, "2026-04-08T00:00:00Z"), 201
        )
        assert accepted["reliance_state"] == "SUBMITTED"
        assert accepted["coverage_from"] == "2026-04-08T00:00:00Z"
        assert accepted["supplier_id"] == env["supplier"]["id"]

    def test_the_buffer_rather_than_bare_intersection_is_what_governs(self, api):
        """PRD 3.5: "Capacity here is exactly one — there is no aggregate allowance,
        adjacency is forbidden, and any gap shorter than the buffer is a collision, so a
        candidate beginning exactly at an existing interval's `coverage_through`
        collides."

        Design: Difficulty/boundary_precision_check/boundary_component_coverage_quarantine_buffer_seven_day_gap_collides_eight_day_gap_clears
        """
        env = _covered_part_env(api)

        # A candidate starting the day after the existing interval ends does not
        # intersect it, yet still falls inside the seven-day quarantine.
        validate_error(
            _candidate_submission(api, env, "2026-04-01T00:00:00Z"),
            ApiErrorId.COMPONENT_COVERAGE_OVERLAP.value,
            409,
        )
        validate_success(_candidate_submission(api, env, "2026-04-08T00:00:00Z"), 201)

        _, meta = validate_paginated(
            api.list_part_certificates(
                params={
                    "component_part_id": env["parts"][0]["id"],
                    "rule_id": env["rules"][0]["id"],
                },
                headers=COORDINATOR_HEADERS,
            )
        )
        assert meta["total_count"] == 2
        assert fx.get_supplier(api, env["supplier"]["id"])["certificates_issued_count"] == 2
