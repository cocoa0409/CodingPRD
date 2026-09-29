"""Chains where each hop exists only because the previous hop fired."""

from test_helpers import fixtures as fx


LEAD_RULE = {
    "hazard_class": "LEAD_CONTENT",
    "severity_weight": 9,
    "limit_value": 100,
    "limit_unit": "PPM",
    "base_method_fee_cents": 18700,
}

FLAT_CATEGORY = {"durable_infant_product": False, "sampling_floor_units": 1}


def _released_batch_env(api):
    """A certified product with one furnished certificate and 400 released units."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    env = fx.distributed_env(
        api,
        rule_specs=[dict(LEAD_RULE)],
        category=dict(FLAT_CATEGORY),
        product={"projected_annual_units": 2000},
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 4},
        measured_value=40,
        certificate_overrides={"manufacture_date_month": "2026-08"},
        batch_specs=[{"quantity": 400, "produced_on": "2026-08-05T00:00:00Z"}],
        release=True,
    )
    assert env["product"]["certification_state"] == "CERTIFIED"
    assert env["product"]["units_released"] == 400
    assert env["product"]["units_held"] == 0

    failing = fx.book_order(
        api,
        env["product"]["id"],
        env["plan"]["id"],
        env["laboratory"]["id"],
        env["rules"][0]["id"],
        sample_count=1,
        window_start="2026-08-10T00:00:00Z",
        window_end="2026-08-12T00:00:00Z",
    )
    fx.start_order(api, failing["id"], env["laboratory"]["id"])
    env["clock"] = fx.set_clock(api, "2026-08-13T00:00:00Z")["current_utc"]
    env["failing_order"] = failing
    return env


class TestFailingResultCascade:
    """Order, product, certificate and batch move on one report."""

    def test_failing_report_suspends_the_product_and_withdraws_its_certificate(self, api):
        """PRD 3.6: "Hop two: the product moves `CERTIFIED → SUSPENDED` or
        `EVIDENCE_COMPLETE → SUSPENDED`, whichever applies, provided the failing order's
        `rule_id` is a member of the product's `required_rule_ids`; its
        `compliance_posture` becomes `SUSPENDED` and its `risk_weighted_gap_score` is
        recomputed." and "Hop three: every children's product certificate of that
        product whose `issuance_status` is `ISSUED` moves to `WITHDRAWN`."

        Design: Difficulty/transitive_cascade/transitive_cascade_failing_result_suspends_product_withdraws_certificate_stops_batch
        """
        env = _released_batch_env(api)
        reported = fx.report(
            api, env["failing_order"]["id"], env["laboratory"]["id"], 250
        )

        assert reported["order_state"] == "REPORTED_FAIL"
        assert reported["result"] == "FAIL"
        assert reported["measured_value"] == 250
        assert reported["reported_at"] == env["clock"]

        product = fx.get_product(api, env["product"]["id"])
        assert product["certification_state"] == "SUSPENDED"
        assert product["compliance_posture"] == "SUSPENDED"

        certificate = fx.get_certificate(api, env["certificate"]["id"])
        assert certificate["issuance_status"] == "WITHDRAWN"
        assert certificate["accompaniment_status"] == "FURNISHED"

    def test_withdrawal_stops_the_released_batch_and_moves_its_units(self, api):
        """PRD 3.6: "Hop four: every production batch referencing a withdrawn
        certificate whose `distribution_state` is `RELEASED` moves `RELEASED →
        STOP_DISTRIBUTION`, moving its `quantity` out of the product's `units_released`
        and into `units_stopped`."

        Design: Difficulty/transitive_cascade/transitive_cascade_failing_result_suspends_product_withdraws_certificate_stops_batch
        """
        env = _released_batch_env(api)
        released_at = env["batches"][0]["released_at"]
        fx.report(api, env["failing_order"]["id"], env["laboratory"]["id"], 250)

        batch = fx.get_batch(api, env["batches"][0]["id"])
        assert batch["distribution_state"] == "STOP_DISTRIBUTION"
        assert batch["released_at"] == released_at
        assert batch["release_rescind_count"] == 0

        product = fx.get_product(api, env["product"]["id"])
        assert product["units_held"] == 0
        assert product["units_released"] == 0
        assert product["units_stopped"] == 400
        assert product["units_destroyed"] == 0

    def test_cascade_opens_one_case_and_leaves_the_earlier_passing_order_alone(self, api):
        """PRD 2.8: "The invariant is that the sum of those four counters equals the
        total `quantity` produced across every batch of the product, with no status
        filter applied to that total."

        Design: Difficulty/transitive_cascade/transitive_cascade_failing_result_suspends_product_withdraws_certificate_stops_batch
        """
        env = _released_batch_env(api)
        fx.report(api, env["failing_order"]["id"], env["laboratory"]["id"], 250)

        summary = fx.get_summary(api, env["product"]["id"])
        assert summary["units_total_produced"] == 400
        assert summary["ledger_balanced"] is True

        case = fx.sole_case_for_product(api, env["product"]["id"])
        assert case["case_state"] == "OPEN"
        assert case["triggering_test_order_id"] == env["failing_order"]["id"]
        assert case["failed_rule_id"] == env["rules"][0]["id"]
        assert case["retest_round_count"] == 0

        passing = fx.get_order(api, env["orders"][0]["id"])
        assert passing["order_state"] == "REPORTED_PASS"


def _relied_upon_env(api):
    """A component-reliance product whose only rule is covered by a supplier certificate."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    env = fx.scoped_product_env(
        api,
        evidence_path="COMPONENT_RELIANCE",
        rule_specs=[dict(LEAD_RULE, component_reliance_allowed=True)],
        category=dict(FLAT_CATEGORY),
        supplier={"reliance_agreement_state": "ON_FILE"},
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 4},
    )
    part = env["parts"][0]
    certificate = fx.submit_part_certificate(
        api,
        part["id"],
        env["supplier"]["id"],
        env["laboratory"]["id"],
        env["rules"][0]["id"],
        measured_value=40,
        coverage_from="2026-01-01T00:00:00Z",
        coverage_through="2026-12-31T00:00:00Z",
    )
    certificate = fx.record_reliance(
        api, certificate["id"], "RELY", "RELIANCE-DOC-2026-0001"
    )
    assert certificate["reliance_state"] == "RELIED_UPON"

    product = fx.get_product(api, env["product"]["id"])
    assert product["certification_state"] == "EVIDENCE_COMPLETE"
    assert product["compliance_posture"] == "CLEARED"

    plan = fx.activate_plan(
        api, fx.create_plan(api, product["id"], plan_type="INITIAL")["id"]
    )
    env["part_certificate"] = certificate
    env["plan"] = plan
    return env


class TestMaterialChangeCascade:
    """A part-level change unwinds reliance, resampling and posture in one call."""

    def test_packaging_only_change_is_recorded_and_moves_nothing_else(self, api):
        """PRD 3.10: "When `triggers_resample` is false — that is, on a `PACKAGING_ONLY`
        change — the contrast is exact and deliberate: no component part row, no
        component-part certificate, no sampling plan and no product posture field is
        touched at all."

        Design: Difficulty/transitive_cascade/transitive_cascade_material_change_supersedes_part_voids_reliance_then_forces_resample_and_restricts_posture
        """
        env = _relied_upon_env(api)
        event = fx.record_material_change(
            api,
            env["product"]["id"],
            subject_type="PRODUCT",
            change_kind="PACKAGING_ONLY",
            description="Outer carton artwork refreshed; nothing the child touches changed.",
        )
        assert event["triggers_resample"] is False

        assert fx.get_part(api, env["parts"][0]["id"])["reliance_status"] == "VALID"
        assert (
            fx.get_part_certificate(api, env["part_certificate"]["id"])["reliance_state"]
            == "RELIED_UPON"
        )
        plan = fx.get_plan(api, env["plan"]["id"])
        assert plan["plan_state"] == "ACTIVE"
        assert plan["resample_trigger"] == "NONE"
        product = fx.get_product(api, env["product"]["id"])
        assert product["compliance_posture"] == "CLEARED"
        assert product["risk_weighted_gap_score"] == 0

    def test_material_substitution_supersedes_the_part_and_voids_its_reliance(self, api):
        """PRD 3.10: "Hop 3 applies only on the `VALID → SUPERSEDED` edge: every
        component-part certificate of that part whose `reliance_state` is `RELIED_UPON`
        moves to `RELIANCE_VOID`."

        Design: Difficulty/transitive_cascade/transitive_cascade_material_change_supersedes_part_voids_reliance_then_forces_resample_and_restricts_posture
        """
        env = _relied_upon_env(api)
        clock = fx.set_clock(api, "2026-08-01T00:00:00Z")["current_utc"]
        event = fx.record_material_change(
            api,
            env["product"]["id"],
            subject_type="COMPONENT_PART",
            component_part_id=env["parts"][0]["id"],
            change_kind="MATERIAL_SUBSTITUTION",
            description="Plasticiser substituted in the coating supplied for this part.",
        )
        assert event["triggers_resample"] is True
        assert event["occurred_at"] == clock
        assert event["subject_type"] == "COMPONENT_PART"
        assert event["component_part_id"] == env["parts"][0]["id"]

        part = fx.get_part(api, env["parts"][0]["id"])
        assert part["reliance_status"] == "SUPERSEDED"
        assert part["last_material_change_at"] == clock

        certificate = fx.get_part_certificate(api, env["part_certificate"]["id"])
        assert certificate["reliance_state"] == "RELIANCE_VOID"
        assert certificate["reliance_documentation_ref"] == "RELIANCE-DOC-2026-0001"

    def test_voided_reliance_forces_resampling_and_restricts_the_posture(self, api):
        """PRD 3.10: "Hop 4 applies regardless of subject type: every `ACTIVE` sampling
        plan of the product moves to `RESAMPLE_DUE`, with `resample_trigger` set to
        `RELIANCE_VOID` when hop 3 actually voided a relied-upon certificate, and to
        `MATERIAL_CHANGE` otherwise."

        Design: Difficulty/transitive_cascade/transitive_cascade_material_change_supersedes_part_voids_reliance_then_forces_resample_and_restricts_posture
        """
        env = _relied_upon_env(api)
        fx.record_material_change(
            api,
            env["product"]["id"],
            subject_type="PRODUCT",
            change_kind="PACKAGING_ONLY",
            description="Outer carton artwork refreshed; nothing the child touches changed.",
        )
        fx.record_material_change(
            api,
            env["product"]["id"],
            subject_type="COMPONENT_PART",
            component_part_id=env["parts"][0]["id"],
            change_kind="MATERIAL_SUBSTITUTION",
            description="Plasticiser substituted in the coating supplied for this part.",
        )

        plan = fx.get_plan(api, env["plan"]["id"])
        assert plan["plan_state"] == "RESAMPLE_DUE"
        assert plan["resample_trigger"] == "RELIANCE_VOID"

        summary = fx.get_summary(api, env["product"]["id"])
        assert summary["compliance_posture"] == "RESTRICTED"
        assert summary["covered_rule_ids"] == []
        assert summary["uncovered_rule_ids"] == [env["rules"][0]["id"]]
        assert summary["resample_due_plan_count"] == 1
        assert summary["risk_weighted_gap_score"] == 100

        assert fx.get_product(api, env["product"]["id"])["material_change_count"] == 2
