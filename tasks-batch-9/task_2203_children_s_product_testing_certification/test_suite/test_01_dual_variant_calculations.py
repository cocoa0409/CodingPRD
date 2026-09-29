"""Two calculations that each carry two coordinated variants."""

from test_helpers import fixtures as fx
from test_helpers import validate_success
from test_helpers.test_users import MANAGER_HEADERS


LEAD_RULE = {
    "hazard_class": "LEAD_CONTENT",
    "severity_weight": 9,
    "periodic_interval_months": 12,
    "limit_value": 90,
    "limit_unit": "PPM",
    "base_method_fee_cents": 10000,
}

DURABLE_CRIB_CATEGORY = {
    "durable_infant_product": True,
    "sampling_floor_units": 4,
    "intended_age_max_months": 36,
}


class TestSamplingSizeVariants:
    """One volume figure, two authorisations."""

    def test_initial_and_periodic_authorisations_diverge_from_one_volume_figure(self, api):
        """PRD 3.5: "For the `INITIAL` variant, divide the product's
        `projected_annual_units` by 2,500 and round the quotient **up** to the next
        whole number to obtain the volume component, then add a base of 3 and
        multiply the sum by the rule count." and "For the `PERIODIC` variant, divide
        the plan's `baseline_units_produced` by 5,000 and round the quotient **down**
        to the preceding whole number to obtain the volume component, then add a base
        of 1 and multiply the sum by the rule count."

        Design: Difficulty/dual_variant_calc/dual_variant_sampling_size_initial_forward_looking_versus_periodic_chronological
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        env = fx.scoped_product_env(
            api,
            evidence_path="FULL_PRODUCT_TEST",
            rule_specs=[dict(LEAD_RULE)],
            category=dict(DURABLE_CRIB_CATEGORY),
            product={"projected_annual_units": 6000},
        )
        assert len(env["product"]["required_rule_ids"]) == 1

        initial = fx.create_plan(api, env["product"]["id"], plan_type="INITIAL")
        periodic = fx.create_plan(
            api,
            env["product"]["id"],
            plan_type="PERIODIC",
            baseline_units_produced=6000,
        )

        assert initial["units_authorized"] == 12
        assert initial["units_committed"] == 0
        assert initial["units_available"] == 12

        assert periodic["units_authorized"] == 4
        assert periodic["units_committed"] == 0
        assert periodic["units_available"] == 4

        assert initial["units_authorized"] - periodic["units_authorized"] == 8

    def test_new_sampling_plans_begin_in_draft_with_no_resample_trigger(self, api):
        """PRD 3.5: "A new plan begins in `plan_state` `DRAFT` with `resample_trigger`
        `NONE`, with `activated_at`, `last_verified_at` and `periodic_due_at` all
        null."

        Design: Difficulty/dual_variant_calc/dual_variant_sampling_size_initial_forward_looking_versus_periodic_chronological
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        env = fx.scoped_product_env(
            api,
            evidence_path="FULL_PRODUCT_TEST",
            rule_specs=[dict(LEAD_RULE)],
            category=dict(DURABLE_CRIB_CATEGORY),
            product={"projected_annual_units": 6000},
        )
        initial = fx.create_plan(api, env["product"]["id"], plan_type="INITIAL")
        periodic = fx.create_plan(
            api,
            env["product"]["id"],
            plan_type="PERIODIC",
            baseline_units_produced=6000,
        )

        for plan in (initial, periodic):
            assert plan["plan_state"] == "DRAFT"
            assert plan["resample_trigger"] == "NONE"
            assert plan["activated_at"] is None
            assert plan["last_verified_at"] is None
            assert plan["periodic_due_at"] is None


def _two_case_distribution_env(api):
    """Two failing rules over one identical pair of released batches."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    env = fx.scoped_product_env(
        api,
        evidence_path="FULL_PRODUCT_TEST",
        rule_specs=[
            dict(LEAD_RULE),
            {
                "hazard_class": "PHTHALATES",
                "severity_weight": 7,
                "periodic_interval_months": 12,
                "limit_value": 1000,
                "limit_unit": "PPM",
                "base_method_fee_cents": 10000,
            },
        ],
        category=dict(DURABLE_CRIB_CATEGORY),
        product={"projected_annual_units": 6000},
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 6},
    )
    product_id = env["product"]["id"]
    lab_id = env["laboratory"]["id"]
    plan = fx.activate_plan(api, fx.create_plan(api, product_id, plan_type="INITIAL")["id"])

    passing = []
    for rule in env["rules"]:
        order = fx.book_order(
            api,
            product_id,
            plan["id"],
            lab_id,
            rule["id"],
            sample_count=1,
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-02T00:00:00Z",
        )
        fx.start_order(api, order["id"], lab_id)
        passing.append(order)
    fx.set_clock(api, "2026-08-02T00:00:00Z")
    for order in passing:
        fx.report(api, order["id"], lab_id, 10)

    current = fx.get_product(api, product_id)
    assert current["certification_state"] == "EVIDENCE_COMPLETE"
    certificate = fx.draft_certificate(
        api, product_id, current["version"], manufacture_date_month="2026-08"
    )
    certificate = fx.issue_certificate(api, certificate["id"])
    fx.furnish_certificate(api, certificate["id"])

    batch_a = fx.create_batch(
        api,
        product_id,
        certificate["id"],
        batch_code="AUR200-000501",
        produced_on="2026-08-05T00:00:00Z",
        quantity=500,
    )
    batch_b = fx.create_batch(
        api,
        product_id,
        certificate["id"],
        batch_code="AUR200-000502",
        produced_on="2026-08-12T00:00:00Z",
        quantity=300,
    )
    # The batches stay HELD: PRD 3.9 refuses the stop-distribution instruction
    # against a case whose product has no batch in HELD or RELEASED, and hop
    # four of the failed-test cascade would already have stopped every RELEASED
    # batch before either case reached the instruction.
    failing = []
    for rule in env["rules"]:
        order = fx.book_order(
            api,
            product_id,
            plan["id"],
            lab_id,
            rule["id"],
            sample_count=1,
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-15T00:00:00Z",
        )
        fx.start_order(api, order["id"], lab_id)
        failing.append(order)
    fx.set_clock(api, "2026-08-16T00:00:00Z")
    for order in failing:
        fx.report(api, order["id"], lab_id, 100000)

    cases = fx.list_cases_for_product(api, product_id)
    assert len(cases) == 2
    by_rule = {case["failed_rule_id"]: case for case in cases}
    return {
        "product_id": product_id,
        "lead_case": by_rule[env["rules"][0]["id"]],
        "phthalate_case": by_rule[env["rules"][1]["id"]],
        "batch_a": batch_a,
        "batch_b": batch_b,
    }


class TestCorrectiveScopeVariants:
    """One batch set, two cutoffs."""

    def test_batch_scoped_and_lot_traceback_scopes_diverge_on_identical_batches(self, api):
        """PRD 3.9: "Under `BATCH_SCOPED`, the operator asserts the defect is confined
        to the material the failing order sampled, and the cutoff is the failing
        order's own `window_start`." and "Under `LOT_TRACEBACK`, the operator cannot
        bound the defect and traces back to the last proof of conformity: the cutoff
        is the greatest `reported_at` among the product's test orders for the same
        `failed_rule_id` whose `order_state` is `REPORTED_PASS` and whose
        `reported_at` precedes the failing order's `reported_at`; when no such earlier
        passing order exists, the cutoff falls back to the product's own `created_at`
        — never to an identifier and never to the beginning of time."

        Design: Difficulty/dual_variant_calc/dual_variant_corrective_scope_batch_scoped_versus_lot_traceback_diverges
        """
        env = _two_case_distribution_env(api)

        batch_scoped = validate_success(
            api.issue_stop_distribution(
                env["lead_case"]["id"],
                {"scope_variant": "BATCH_SCOPED"},
                headers=MANAGER_HEADERS,
            ),
            200,
        )
        lot_traceback = validate_success(
            api.issue_stop_distribution(
                env["phthalate_case"]["id"],
                {"scope_variant": "LOT_TRACEBACK"},
                headers=MANAGER_HEADERS,
            ),
            200,
        )

        assert batch_scoped["scope_variant"] == "BATCH_SCOPED"
        assert batch_scoped["case_state"] == "STOP_DISTRIBUTION_ISSUED"
        assert batch_scoped["scope_units"] == 300

        assert lot_traceback["scope_variant"] == "LOT_TRACEBACK"
        assert lot_traceback["case_state"] == "STOP_DISTRIBUTION_ISSUED"
        assert lot_traceback["scope_units"] == 800

        assert lot_traceback["scope_units"] - batch_scoped["scope_units"] == 500

    def test_stop_distribution_leaves_batches_already_stopped_where_they_are(self, api):
        """PRD 3.9: "In both variants the in-scope set is every production batch of
        the case's product whose `distribution_state` is anything other than
        `DESTROYED` and whose `produced_on` is at or after the cutoff."

        Design: Difficulty/dual_variant_calc/dual_variant_corrective_scope_batch_scoped_versus_lot_traceback_diverges
        """
        env = _two_case_distribution_env(api)
        fx.issue_stop_distribution(api, env["lead_case"]["id"], "BATCH_SCOPED")
        fx.issue_stop_distribution(api, env["phthalate_case"]["id"], "LOT_TRACEBACK")

        for batch in (env["batch_a"], env["batch_b"]):
            assert fx.get_batch(api, batch["id"])["distribution_state"] == "STOP_DISTRIBUTION"

        product = fx.get_product(api, env["product_id"])
        assert product["units_stopped"] == 800
        assert product["units_released"] == 0
        assert product["units_held"] == 0
        assert product["units_destroyed"] == 0
        summary = fx.get_summary(api, env["product_id"])
        assert summary["units_total_produced"] == 800
        assert summary["ledger_balanced"] is True
