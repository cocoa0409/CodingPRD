"""Two shared resources booked over intervals, under opposite interval semantics."""

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    COORDINATOR_HEADERS,
    OFFICER_HEADERS,
    make_supplier_user_headers,
)


FLAT_CATEGORY = {"durable_infant_product": False, "sampling_floor_units": 1}

LEAD_RULE = {
    "hazard_class": "LEAD_CONTENT",
    "severity_weight": 9,
    "limit_value": 100,
    "limit_unit": "PPM",
    "base_method_fee_cents": 18700,
}

WINDOW_A = ("2026-08-02T00:00:00Z", "2026-08-06T00:00:00Z")
WINDOW_B = ("2026-08-03T00:00:00Z", "2026-08-07T00:00:00Z")
WINDOW_THIRD_OVERLAP = ("2026-08-04T00:00:00Z", "2026-08-05T00:00:00Z")
WINDOW_ADJACENT = ("2026-08-06T00:00:00Z", "2026-08-08T00:00:00Z")


def _two_slot_laboratory_env(api):
    """A capacity-two laboratory already carrying two overlapping orders."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    env = fx.booking_env(
        api,
        rule_specs=[dict(LEAD_RULE)],
        category=dict(FLAT_CATEGORY),
        product={"projected_annual_units": 6000},
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 2},
        accreditation_overrides=[{"fee_surcharge_basis_points": 0}],
        plan_overrides={"plan_type": "INITIAL"},
    )
    assert env["plan"]["units_authorized"] == 6

    env["order_a"] = _book(api, env, WINDOW_A)
    env["order_b"] = _book(api, env, WINDOW_B)
    return env


def _candidate_payload(env, window):
    return factories.test_order_payload(
        env["product"]["id"],
        env["plan"]["id"],
        env["laboratory"]["id"],
        env["rules"][0]["id"],
        sample_count=1,
        window_start=window[0],
        window_end=window[1],
    )


def _book(api, env, window):
    return validate_success(
        api.create_test_order(_candidate_payload(env, window), headers=COORDINATOR_HEADERS),
        201,
    )


class TestLaboratorySlotAggregateCapacity:
    """Overlap is legal up to the aggregate ceiling, and adjacency never counts."""

    def test_two_overlapping_orders_fit_a_capacity_of_two(self, api):
        """PRD 3.6: "Only when peak concurrency **exceeds** the laboratory's
        `concurrent_slot_capacity` is the booking refused, with
        `ERR_LAB_SLOT_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/temporal_overlap_laboratory_slots_half_open_aggregate_capacity_two_with_adjacency_allowed
        """
        env = _two_slot_laboratory_env(api)
        assert env["order_a"]["order_state"] == "SCHEDULED"
        assert env["order_b"]["order_state"] == "SCHEDULED"
        assert env["order_a"]["window_start"] == WINDOW_A[0]
        assert env["order_b"]["window_end"] == WINDOW_B[1]
        assert len(fx.list_orders_for_product(api, env["product"]["id"])) == 2

    def test_a_third_order_inside_both_windows_exceeds_the_capacity(self, api):
        """PRD 3.6: "At each breakpoint, the concurrency is 1 — the candidate always
        contributes exactly one — plus the number of existing orders whose `window_start`
        is at or before that instant and whose `window_end` is strictly after it."

        Design: Difficulty/resource_temporal_overlap/temporal_overlap_laboratory_slots_half_open_aggregate_capacity_two_with_adjacency_allowed
        """
        env = _two_slot_laboratory_env(api)
        validate_error(
            api.create_test_order(
                _candidate_payload(env, WINDOW_THIRD_OVERLAP), headers=COORDINATOR_HEADERS
            ),
            ApiErrorId.LAB_SLOT_CAPACITY_EXCEEDED.value,
            409,
        )
        plan = fx.get_plan(api, env["plan"]["id"])
        assert plan["units_committed"] == 2
        assert plan["units_available"] == 4

    def test_a_window_beginning_where_another_ends_is_accepted(self, api):
        """PRD 3.6: "Adjacency is therefore permitted: an existing order ending exactly
        when the candidate begins does not overlap it, because the existing window
        excludes its own end instant."

        Design: Difficulty/resource_temporal_overlap/temporal_overlap_laboratory_slots_half_open_aggregate_capacity_two_with_adjacency_allowed
        """
        env = _two_slot_laboratory_env(api)
        api.create_test_order(
            _candidate_payload(env, WINDOW_THIRD_OVERLAP), headers=COORDINATOR_HEADERS
        )
        adjacent = _book(api, env, WINDOW_ADJACENT)
        assert adjacent["order_state"] == "SCHEDULED"
        assert adjacent["window_start"] == WINDOW_A[1]

    def test_cancelling_an_order_frees_its_window_immediately(self, api):
        """PRD 3.6: "Consider only orders at the same laboratory whose `order_state` is
        `SCHEDULED` or `IN_TESTING`; orders in `CANCELLED`, `INVALIDATED`,
        `REPORTED_PASS` or `REPORTED_FAIL` have released their window and are excluded."

        Design: Difficulty/resource_temporal_overlap/temporal_overlap_laboratory_slots_half_open_aggregate_capacity_two_with_adjacency_allowed
        """
        env = _two_slot_laboratory_env(api)
        api.create_test_order(
            _candidate_payload(env, WINDOW_THIRD_OVERLAP), headers=COORDINATOR_HEADERS
        )
        _book(api, env, WINDOW_ADJACENT)

        cancelled = validate_success(
            api.cancel_test_order(env["order_b"]["id"], headers=COORDINATOR_HEADERS), 200
        )
        assert cancelled["order_state"] == "CANCELLED"

        retried = _book(api, env, WINDOW_THIRD_OVERLAP)
        assert retried["order_state"] == "SCHEDULED"

        plan = fx.get_plan(api, env["plan"]["id"])
        assert plan["units_authorized"] == 6
        assert plan["units_committed"] == 3
        assert plan["units_available"] == 3

        laboratory = fx.get_laboratory(api, env["laboratory"]["id"])
        assert laboratory["billed_fee_cents_total"] == 74800
        assert laboratory["credited_fee_cents_total"] == 18700


SHELL_COVERAGE = ("2026-01-01T00:00:00Z", "2026-03-31T00:00:00Z")
STRICT_OVERLAP = ("2026-03-01T00:00:00Z", "2026-05-31T00:00:00Z")
INSIDE_BUFFER = ("2026-04-03T00:00:00Z", "2026-06-30T00:00:00Z")


def _two_part_reliance_env(api):
    """Two sibling parts under two reliance-eligible rules, one interval already taken."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    env = fx.scoped_product_env(
        api,
        evidence_path="COMPONENT_RELIANCE",
        rule_specs=[
            dict(LEAD_RULE, component_reliance_allowed=True),
            {
                "hazard_class": "PHTHALATES",
                "severity_weight": 4,
                "limit_value": 1000,
                "limit_unit": "PPM",
                "base_method_fee_cents": 18700,
                "component_reliance_allowed": True,
            },
        ],
        category=dict(FLAT_CATEGORY),
        part_specs=[
            {"part_name": "Moulded shell", "material_class": "PAINTED_COATING"},
            {"part_name": "Handlebar grip", "material_class": "PAINTED_COATING"},
        ],
        supplier={"reliance_agreement_state": "ON_FILE"},
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 4},
    )
    env["shell"], env["grip"] = env["parts"]
    env["lead_rule"], env["phthalate_rule"] = env["rules"]
    env["shell_lead_certificate"] = fx.submit_part_certificate(
        api,
        env["shell"]["id"],
        env["supplier"]["id"],
        env["laboratory"]["id"],
        env["lead_rule"]["id"],
        measured_value=40,
        coverage_from=SHELL_COVERAGE[0],
        coverage_through=SHELL_COVERAGE[1],
    )
    return env


def _submit(api, env, part, rule, coverage):
    return api.submit_part_certificate(
        part["id"],
        factories.part_certificate_payload(
            env["laboratory"]["id"],
            rule["id"],
            measured_value=40,
            coverage_from=coverage[0],
            coverage_through=coverage[1],
        ),
        headers=make_supplier_user_headers(env["supplier"]["id"]),
    )


class TestComponentCoverageSlotIsOnePerPartAndRule:
    """Capacity one, buffered on both sides, keyed on the part-and-rule pair."""

    def test_any_overlap_at_all_is_fatal_for_the_same_part_and_rule(self, api):
        """PRD 3.5: "Coverage intervals for the same part-and-rule pair are kept strictly
        apart, with a mandatory quarantine buffer of one week — seven days — between
        consecutive intervals."

        Design: Difficulty/resource_temporal_overlap/temporal_overlap_component_coverage_closed_buffered_exclusive_capacity_one_per_part_rule_pair
        """
        env = _two_part_reliance_env(api)
        validate_error(
            _submit(api, env, env["shell"], env["lead_rule"], STRICT_OVERLAP),
            ApiErrorId.COMPONENT_COVERAGE_OVERLAP.value,
            409,
        )
        validate_error(
            _submit(api, env, env["shell"], env["lead_rule"], INSIDE_BUFFER),
            ApiErrorId.COMPONENT_COVERAGE_OVERLAP.value,
            409,
        )

    def test_a_different_rule_or_a_sibling_part_may_hold_the_same_interval(self, api):
        """PRD 3.5: "The check considers only existing certificates for the same
        `component_part_id` and the same `rule_id` whose `reliance_state` is `SUBMITTED`
        or `RELIED_UPON`; rows in `REJECTED` or `RELIANCE_VOID` free their interval and
        are ignored."

        Design: Difficulty/resource_temporal_overlap/temporal_overlap_component_coverage_closed_buffered_exclusive_capacity_one_per_part_rule_pair
        """
        env = _two_part_reliance_env(api)

        same_part_other_rule = validate_success(
            _submit(api, env, env["shell"], env["phthalate_rule"], SHELL_COVERAGE), 201
        )
        assert same_part_other_rule["coverage_from"] == SHELL_COVERAGE[0]
        assert same_part_other_rule["rule_id"] == env["phthalate_rule"]["id"]

        sibling_part_same_rule = validate_success(
            _submit(api, env, env["grip"], env["lead_rule"], SHELL_COVERAGE), 201
        )
        assert sibling_part_same_rule["component_part_id"] == env["grip"]["id"]
        assert sibling_part_same_rule["coverage_from"] == SHELL_COVERAGE[0]

    def test_rejecting_a_certificate_frees_its_interval_for_reuse(self, api):
        """PRD 3.5: "Choosing `REJECT` moves the certificate `SUBMITTED → REJECTED`."

        Design: Difficulty/resource_temporal_overlap/temporal_overlap_component_coverage_closed_buffered_exclusive_capacity_one_per_part_rule_pair
        """
        env = _two_part_reliance_env(api)
        _submit(api, env, env["shell"], env["lead_rule"], STRICT_OVERLAP)
        _submit(api, env, env["shell"], env["lead_rule"], INSIDE_BUFFER)
        validate_success(
            _submit(api, env, env["shell"], env["phthalate_rule"], SHELL_COVERAGE), 201
        )

        rejected = validate_success(
            api.record_reliance_documentation(
                env["shell_lead_certificate"]["id"],
                {
                    "reliance_decision": "REJECT",
                    "reliance_documentation_ref": "REL-2026-REJ-0007",
                },
                headers=OFFICER_HEADERS,
            ),
            200,
        )
        assert rejected["reliance_state"] == "REJECTED"

        retried = validate_success(
            _submit(api, env, env["shell"], env["lead_rule"], STRICT_OVERLAP), 201
        )
        assert retried["coverage_from"] == STRICT_OVERLAP[0]

        _, meta = validate_paginated(
            api.list_part_certificates(
                params={"component_part_id": env["shell"]["id"]},
                headers=COORDINATOR_HEADERS,
            )
        )
        assert meta["total_count"] == 3
